from datetime import date, timedelta
import itertools
import random
from sqlmodel import Session, select
from src.models import Conference, Division, Game


def round_robin_polygon(team_ids: list[int], repeats: int = 1) -> list[tuple[int, int]]:
    """Generates round-robin matchups using the standard circle/polygon algorithm.
    
    Ensures every team plays 1 game per round without collision, while alternating
    home/away hosting responsibilities.
    """
    pool = list(team_ids)
    if len(pool) % 2 != 0:
        pool.append(None)

    n = len(pool)
    rounds = []

    for r in range(n - 1):
        round_matches = []
        for i in range(n // 2):
            t1, t2 = pool[i], pool[n - 1 - i]
            if t1 is not None and t2 is not None:
                round_matches.append((t1, t2) if r % 2 == 0 else (t2, t1))
        rounds.append(round_matches)
        pool = [pool[0]] + [pool[-1]] + pool[1:-1]

    all_matches = []
    for cycle in range(repeats):
        for rnd in rounds:
            matchups = [(b, a) if cycle % 2 == 1 else (a, b) for a, b in rnd]
            all_matches.extend(matchups)

    return all_matches


def generate_season_schedule(
    session: Session, start_date: date = date(2026, 10, 8), daily_cap: int = 8
) -> int:
    """Traverses 3NF tables (Conferences -> Divisions -> Teams) to generate all matchups."""
    
    # 1. Clear previous games
    session.query(Game).delete()
    session.commit()

    # 2. Query team groups using 3NF relationships
    divisions = session.exec(select(Division)).all()
    conferences = session.exec(select(Conference)).all()

    matchups: list[tuple[int, int, str]] = []

    # Tier 1: Divisional Games (4 rounds within each 8-team division)
    for div in divisions:
        div_team_ids = [t.id for t in div.teams]
        div_pairs = round_robin_polygon(div_team_ids, repeats=4)
        matchups.extend([(h, a, "Divisional") for h, a in div_pairs])

    # Tier 2: Inter-Conference Games (1 Home + 1 Away vs each team in opposite conference)
    east_teams = []
    west_teams = []
    for conf in conferences:
        for div in conf.divisions:
            if conf.name == "Eastern":
                east_teams.extend([t.id for t in div.teams])
            elif conf.name == "Western":
                west_teams.extend([t.id for t in div.teams])

    for e_id, w_id in itertools.product(east_teams, west_teams):
        matchups.append((e_id, w_id, "Inter-Conference"))
        matchups.append((w_id, e_id, "Inter-Conference"))

    # 3. Shuffle matches
    random.seed(42)
    random.shuffle(matchups)

    # 4. Map matchups onto calendar dates
    games_to_create: list[Game] = []
    current_date = start_date

    for i, (home_id, away_id, gtype) in enumerate(matchups):
        if i > 0 and i % daily_cap == 0:
            current_date += timedelta(days=1)

        games_to_create.append(
            Game(
                game_date=current_date,
                home_team_id=home_id,
                away_team_id=away_id,
                game_type=gtype,
            )
        )

    # 5. Bulk commit
    session.add_all(games_to_create)
    session.commit()

    return len(games_to_create)