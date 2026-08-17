from contextlib import asynccontextmanager
from typing import Optional
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import JSONResponse, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session, select

from .database import get_session, init_db
from .generate import generate_season_schedule
from .models import Conference, Division, Game, Team


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Ensures tables and initial team seeds exist on application startup."""
    try:
        init_db()
    except Exception as e:
        print(f"CRITICAL: Failed database startup initialization: {e}")
    yield


# Disable default CDN docs
app = FastAPI(
    title="NHL Season Scheduler API",
    description="REST API for generating and querying 3NF-normalized NHL regular season schedules.",
    version="1.1.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
)

# Mount local static files
STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ---------------------------------------------------------------------------
# Frontend Dashboard Routes (This fixes the 404!)
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def serve_dashboard():
    """Serves the NHL Midnight Ice Dashboard UI."""
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return HTMLResponse("<h2>Frontend UI is loading... Please ensure static/index.html exists.</h2>")


@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui_html():
    """Renders Swagger UI strictly from offline local static assets."""
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=f"{app.title} - Swagger UI",
        swagger_js_url="/static/swagger-ui-bundle.js",
        swagger_css_url="/static/swagger-ui.css",
    )


# Global catch-all exception handler for unexpected 500 errors
@app.exception_handler(Exception)
async def global_exception_handler(request, exc: Exception):
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "InternalServerError",
            "message": "An unexpected error occurred processing your request.",
            "detail": str(exc),
        },
    )


# ---------------------------------------------------------------------------
# 1. Schedule Generation Endpoints
# ---------------------------------------------------------------------------
@app.post(
    "/schedule/generate",
    status_code=status.HTTP_201_CREATED,
    tags=["Schedule Engine"],
)
def trigger_schedule_generation(
    daily_cap: int = Query(
        8, ge=1, le=16, description="Max games per day (between 1 and 16)"
    ),
    session: Session = Depends(get_session),
):
    """Executes the round-robin polygon algorithm and batch-commits games to SQLite."""
    try:
        total_games = generate_season_schedule(session, daily_cap=daily_cap)
        return {
            "status": "success",
            "message": f"Successfully generated {total_games} regular-season games.",
            "total_games_scheduled": total_games, # UI uses this key
            "daily_cap": daily_cap
        }
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate schedule: {str(e)}",
        )


@app.get("/schedule/all", tags=["Schedule Engine"])
def get_full_schedule(
    limit: int = Query(default=2000, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session)
):
    """Fetch the full schedule mapped with team names for the UI."""
    teams = {t.id: t.name for t in session.exec(select(Team)).all()}
    
    # Assuming your model uses game_day for the day of the season
    statement = select(Game).order_by(Game.game_day).offset(offset).limit(limit)
    games = session.exec(statement).all()
    
    return [
        {
            "id": g.id,
            "game_day": g.game_day,
            "date": getattr(g, "game_date", None), 
            "home_team_id": g.home_team_id,
            "home_team_name": teams.get(g.home_team_id, "Unknown"),
            "away_team_id": g.away_team_id,
            "away_team_name": teams.get(g.away_team_id, "Unknown"),
            "game_type": getattr(g, "game_type", "Regular")
        }
        for g in games
    ]


# ---------------------------------------------------------------------------
# 2. Hierarchy Query Endpoints
# ---------------------------------------------------------------------------
@app.get(
    "/conferences",
    response_model=list[Conference],
    status_code=status.HTTP_200_OK,
    tags=["League Hierarchy"],
)
def get_conferences(session: Session = Depends(get_session)):
    """Fetch all parent conferences."""
    return session.exec(select(Conference)).all()


@app.get(
    "/divisions",
    response_model=list[Division],
    status_code=status.HTTP_200_OK,
    tags=["League Hierarchy"],
)
def get_divisions(
    conference_id: Optional[int] = None, session: Session = Depends(get_session)
):
    """Fetch divisions, optionally filtered by conference ID."""
    query = select(Division)
    if conference_id is not None:
        query = query.where(Division.conference_id == conference_id)
    return session.exec(query).all()


# ---------------------------------------------------------------------------
# 3. Teams and Games Endpoints
# ---------------------------------------------------------------------------
@app.get(
    "/teams",
    status_code=status.HTTP_200_OK,
    tags=["Teams"],
)
def get_teams(session: Session = Depends(get_session)):
    """List NHL franchises joined with their division and conference names."""
    statement = (
        select(Team, Division, Conference)
        .join(Division, Team.division_id == Division.id)
        .join(Conference, Division.conference_id == Conference.id)
        .order_by(Team.name)
    )
    results = session.exec(statement).all()
    
    return [
        {
            "id": team.id,
            "name": team.name,
            "division_id": team.division_id,
            "division_name": division.name,
            "conference_name": conference.name
        }
        for team, division, conference in results
    ]


@app.get(
    "/teams/{team_identifier}/games",
    status_code=status.HTTP_200_OK,
    tags=["Schedule Engine"],
)
def get_team_schedule(
    team_identifier: str,
    session: Session = Depends(get_session),
):
    """Fetch every scheduled matchup for a team by ID or Name."""
    if team_identifier.isdigit():
        team = session.get(Team, int(team_identifier))
    else:
        team = session.exec(
            select(Team).where(Team.name.ilike(f"%{team_identifier.strip()}%"))
        ).first()

    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Team '{team_identifier}' does not exist.",
        )

    teams = {t.id: t.name for t in session.exec(select(Team)).all()}
    
    query = (
        select(Game)
        .where((Game.home_team_id == team.id) | (Game.away_team_id == team.id))
        .order_by(Game.game_day)
    )
    games = session.exec(query).all()

    return {
        "team_id": team.id,
        "team_name": team.name,
        "total_games": len(games),
        "schedule": [
            {
                "id": g.id,
                "game_day": g.game_day,
                "date": getattr(g, "game_date", None),
                "home_team_id": g.home_team_id,
                "home_team_name": teams.get(g.home_team_id, "Unknown"),
                "away_team_id": g.away_team_id,
                "away_team_name": teams.get(g.away_team_id, "Unknown"),
                "is_home": (g.home_team_id == team.id),
                "opponent": teams.get(g.away_team_id if g.home_team_id == team.id else g.home_team_id, "Unknown"),
                "game_type": getattr(g, "game_type", "Regular")
            }
            for g in games
        ]
    }