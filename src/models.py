from datetime import date
from typing import Optional
from sqlmodel import Field, Relationship, SQLModel


class Conference(SQLModel, table=True):
    __tablename__ = "conferences"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)

    divisions: list["Division"] = Relationship(back_populates="conference")


class Division(SQLModel, table=True):
    __tablename__ = "divisions"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    conference_id: int = Field(foreign_key="conferences.id", index=True)

    conference: Optional[Conference] = Relationship(back_populates="divisions")
    teams: list["Team"] = Relationship(back_populates="division")


class Team(SQLModel, table=True):
    __tablename__ = "teams"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    division_id: int = Field(foreign_key="divisions.id", index=True)

    division: Optional[Division] = Relationship(back_populates="teams")


class Game(SQLModel, table=True):
    __tablename__ = "games"

    id: Optional[int] = Field(default=None, primary_key=True)
    game_date: date = Field(index=True)
    home_team_id: int = Field(foreign_key="teams.id", index=True)
    away_team_id: int = Field(foreign_key="teams.id", index=True)
    game_type: str