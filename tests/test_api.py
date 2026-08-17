from collections.abc import Generator
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from src.database import get_session
from src.main import app
from src.models import Conference, Division, Team

@pytest.fixture(name="session")
def session_fixture() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        # 1. Manually create a fake league in the test database
        conf = Conference(name="Test Conference")
        session.add(conf)
        session.commit()

        div = Division(name="Test Division", conference_id=conf.id)
        session.add(div)
        session.commit()

        # 2. Add an even number of teams so the scheduling algorithm works
        for i in range(4):
            session.add(Team(name=f"Test Team {i}", division_id=div.id))
        session.commit()

        yield session

    SQLModel.metadata.drop_all(engine)

@pytest.fixture(name="client")
def client_fixture(session: Session) -> Generator[TestClient, None, None]:
    def get_session_override():
        return session

    app.dependency_overrides[get_session] = get_session_override
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()

def test_get_teams(client: TestClient):
    response = client.get("/teams")
    assert response.status_code == 200
    assert len(response.json()) > 0  # This will now pass because we added 4 teams!

def test_generate_schedule_success(client: TestClient):
    response = client.post("/schedule/generate?daily_cap=10")
    assert response.status_code == 201

def test_generate_schedule_validation_failure(client: TestClient):
    response = client.post("/schedule/generate?daily_cap=25")
    assert response.status_code == 422

def test_get_team_schedule_not_found(client: TestClient):
    response = client.get("/teams/9999/games")
    assert response.status_code == 404