from contextlib import asynccontextmanager
from typing import Optional
from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import JSONResponse
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
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
)

# Mount local static files
app.mount("/static", StaticFiles(directory="src/static"), name="static")


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
            "total_games": total_games,
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
    try:
        return session.exec(select(Conference)).all()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error reading conferences: {str(e)}",
        )


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
    try:
        query = select(Division)
        if conference_id is not None:
            if not session.get(Conference, conference_id):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Conference with ID {conference_id} not found.",
                )
            query = query.where(Division.conference_id == conference_id)
        return session.exec(query).all()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error reading divisions: {str(e)}",
        )


# ---------------------------------------------------------------------------
# 3. Teams and Games Endpoints
# ---------------------------------------------------------------------------
@app.get(
    "/teams",
    response_model=list[Team],
    status_code=status.HTTP_200_OK,
    tags=["Teams"],
)
def get_teams(
    division_id: Optional[int] = None, session: Session = Depends(get_session)
):
    """List NHL franchises, optionally filtered by division ID."""
    try:
        query = select(Team)
        if division_id is not None:
            if not session.get(Division, division_id):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Division with ID {division_id} not found.",
                )
            query = query.where(Team.division_id == division_id)
        return session.exec(query).all()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error reading teams: {str(e)}",
        )


@app.get(
    "/teams/{team_id}/games",
    response_model=list[Game],
    status_code=status.HTTP_200_OK,
    tags=["Schedule Engine"],
)
def get_team_schedule(
    team_id: int,
    game_type: Optional[str] = Query(
        None,
        description="Filter by type: 'Divisional' or 'Inter-Conference'",
    ),
    session: Session = Depends(get_session),
):
    """Fetch every scheduled matchup for a team (Home and Away)."""
    try:
        team = session.get(Team, team_id)
        if not team:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Team with ID {team_id} does not exist.",
            )

        query = (
            select(Game)
            .where(
                (Game.home_team_id == team_id) | (Game.away_team_id == team_id)
            )
            .order_by(Game.game_date)
        )

        if game_type:
            query = query.where(Game.game_type == game_type)

        return session.exec(query).all()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching games: {str(e)}",
        )