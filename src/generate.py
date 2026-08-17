from datetime import date, timedelta
from sqlmodel import Session, select
from src.models import Team, Game


def generate_season_schedule(session: Session, daily_cap: int = 8) -> int:
    """
    Generates a full regular-season schedule using a round-robin algorithm,
    distributes the games across a realistic ~185-day NHL calendar window 
    (October to April), respects the daily concurrency cap, and commits them.
    """
    # 1. Clear out any old schedule before generating a new one
    session.query(Game).delete()
    session.commit()

    # 2. Fetch all teams from the database
    teams = session.exec(select(Team)).all()
    team_ids = [t.id for t in teams]
    n = len(team_ids)

    if n < 2:
        raise ValueError("Not enough teams in the database to generate a schedule.")

    # Ensure even number of teams for round-robin (add a bye placeholder if needed)
    has_bye = n % 2 != 0
    if has_bye:
        team_ids.append(None)
        n += 1

    # 3. Polygon Round-Robin Algorithm (Collect all individual matchups)
    all_matchups = []
    rotating_teams = team_ids[1:]
    fixed_team = team_ids[0]

    total_passes = 4  # Multi-pass rotation to build out the 82-game framework
    for pass_num in range(total_passes):
        current_rotating = rotating_teams[:]
        shift_amount = pass_num % len(current_rotating)
        current_rotating = (
            current_rotating[shift_amount:] + current_rotating[:shift_amount]
        )

        rounds_in_pass = len(team_ids) - 1
        for r in range(rounds_in_pass):
            round_matchups = []

            # Pair the fixed team with the last element of the rotated list
            team_a = fixed_team
            team_b = current_rotating[-1]

            if team_a is not None and team_b is not None:
                if (r + pass_num) % 2 == 0:
                    round_matchups.append((team_a, team_b, "Divisional"))
                else:
                    round_matchups.append((team_b, team_a, "Divisional"))

            # Pair the rest
            half = len(current_rotating) // 2
            for i in range(half):
                t1 = current_rotating[i]
                t2 = current_rotating[len(current_rotating) - 2 - i]

                if t1 is not None and t2 is not None:
                    if (i + r) % 2 == 0:
                        round_matchups.append((t1, t2, "Regular"))
                    else:
                        round_matchups.append((t2, t1, "Regular"))

            all_matchups.extend(round_matchups)
            current_rotating = [current_rotating[-1]] + current_rotating[:-1]

    # 4. Map matchups across a realistic ~185 game-day calendar (Oct to April)
    season_start = date(2026, 10, 6)   # Opening Night
    season_end = date(2027, 4, 12)     # Regular Season Finale
    
    # Generate a list of available calendar dates, filtering out occasional empty days if desired,
    # or stepping smoothly across the window. Let's build a clean list of target game dates.
    total_calendar_days = (season_end - season_start).days
    calendar_dates = [season_start + timedelta(days=i) for i in range(total_calendar_days + 1)]

    games_to_create = []
    matchup_index = 0
    total_matchups = len(all_matchups)

    # Distribute games day-by-day across the calendar window respecting the daily_cap
    day_counter = 1
    for current_date in calendar_dates:
        if matchup_index >= total_matchups:
            break

        # Determine how many games to play on this specific day (up to daily_cap)
        games_today_count = min(daily_cap, total_matchups - matchup_index)
        
        for _ in range(games_today_count):
            home_id, away_id, gtype = all_matchups[matchup_index]
            games_to_create.append(
                Game(
                    game_day=day_counter,
                    game_date=current_date,
                    home_team_id=home_id,
                    away_team_id=away_id,
                    game_type=gtype,
                )
            )
            matchup_index += 1

        day_counter += 1

    # If there are any leftover matchups due to capping, dump them on the final day
    while matchup_index < total_matchups:
        home_id, away_id, gtype = all_matchups[matchup_index]
        games_to_create.append(
            Game(
                game_day=day_counter - 1,
                game_date=season_end,
                home_team_id=home_id,
                away_team_id=away_id,
                game_type=gtype,
            )
        )
        matchup_index += 1

    # 5. Batch insert everything into SQLite in a single transaction commit
    session.add_all(games_to_create)
    session.commit()

    return len(games_to_create)