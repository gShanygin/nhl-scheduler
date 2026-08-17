from sqlmodel import Session, SQLModel, create_engine, select
from src.models import Conference, Division, Team
from sqlmodel import Session, SQLModel, create_engine
from sqlalchemy import event

sqlite_file_name = "nhl.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"

# check_same_thread=False is needed for FastAPI
engine = create_engine(sqlite_url, connect_args={"check_same_thread": False})

# --- Add this block to speed up SQLite writes ---
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()
DATABASE_URL = "sqlite:///./nhl_schedule.db"

# connect_args={"check_same_thread": False} is required for SQLite when accessed across FastAPI threads
engine = create_engine(
    DATABASE_URL, echo=False, connect_args={"check_same_thread": False}
)

# 3NF Hierarchical data: Conference -> Division -> Teams
LEAGUE_HIERARCHY = {
    "Eastern": {
        "Atlantic": [
            "Boston Bruins",
            "Buffalo Sabres",
            "Detroit Red Wings",
            "Florida Panthers",
            "Montreal Canadiens",
            "Ottawa Senators",
            "Tampa Bay Lightning",
            "Toronto Maple Leafs",
        ],
        "Metropolitan": [
            "Carolina Hurricanes",
            "Columbus Blue Jackets",
            "New Jersey Devils",
            "New York Islanders",
            "New York Rangers",
            "Philadelphia Flyers",
            "Pittsburgh Penguins",
            "Washington Capitals",
        ],
    },
    "Western": {
        "Central": [
            "Chicago Blackhawks",
            "Colorado Avalanche",
            "Dallas Stars",
            "Minnesota Wild",
            "Nashville Predators",
            "St. Louis Blues",
            "Utah Mammoth",
            "Winnipeg Jets",
        ],
        "Pacific": [
            "Anaheim Ducks",
            "Calgary Flames",
            "Edmonton Oilers",
            "Los Angeles Kings",
            "San Jose Sharks",
            "Seattle Kraken",
            "Vancouver Canucks",
            "Vegas Golden Knights",
        ],
    },
}


def init_db():
    """Initializes tables and seeds Conferences, Divisions, and Teams."""
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        # Check if already seeded to prevent duplicate inserts
        if session.exec(select(Conference)).first():
            return

        for conf_name, divisions in LEAGUE_HIERARCHY.items():
            conf = Conference(name=conf_name)
            session.add(conf)
            session.flush()  # Flushes to generate conf.id in SQLite

            for div_name, team_names in divisions.items():
                div = Division(name=div_name, conference_id=conf.id)
                session.add(div)
                session.flush()  # Flushes to generate div.id in SQLite

                for t_name in team_names:
                    team = Team(name=t_name, division_id=div.id)
                    session.add(team)

        session.commit()


def get_session():
    """FastAPI dependency for yielding scoped database sessions."""
    with Session(engine) as session:
        yield session