import asyncpg
import os
import json

_pool: asyncpg.Pool = None

async def init_db():
    global _pool
    _pool = await asyncpg.create_pool(
        dsn=os.environ["DATABASE_URL"],
        min_size=1,
        max_size=5, # the 6th connectionexion will wait in the queue until one is released
    )
    print("DB pool ready")

async def close_db():
    if _pool:
        await _pool.close()

def get_pool():
    return _pool

async def save_match(players_info: list, score: dict, elo_deltas: dict):
    if _pool is None:
        print("[DB] Pool not initialized, skipping save")
        return

    async with _pool.acquire() as connection: # aquires a connectionection from the pool and releases it back when done or if an exception occurs
        async with connection.transaction(): # ensures that all DB operations in this block are atomic. If any fail, the transaction is cancelled and the DB remains consistent

            # Retrieve the current IDs and ELO ratings from the usernames in players_info
            player_ids = {}
            for p in players_info:
                row = await connection.fetchrow(
                    "SELECT id, elo FROM players WHERE username = $1",
                    p["username"]
                ) # fetchrow returns None if no line is found or it returns a Record object with the columns as attributes (id, username, elo)
                if row is None:
                    print(f"[DB] Player '{p['username']}' not found, skipping match save")
                    return
                player_ids[p["username"]] = row["id"]

            # Check if it's 1v1 or 2v2, insert the match accordingly and get the match_id
            is_2v2 = len(players_info) == 4

            if not is_2v2:
                red_player  = next(p for p in players_info if p["team"] == "red")
                blue_player = next(p for p in players_info if p["team"] == "blue")

                match_id = await connection.fetchval( # returns the value of the first column of the first row of the result (match_id returned)
                    """
                    INSERT INTO matches_1v1
                        (player_red_id, player_blue_id,
                         score_red, score_blue,
                         elo_delta_red, elo_delta_blue)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    RETURNING id
                    """,
                    player_ids[red_player["username"]],
                    player_ids[blue_player["username"]],
                    score["red"],
                    score["blue"],
                    elo_deltas.get("red", 0), # if it's a 2v2 there is no red key, so we default to 0 for no elo variations
                    elo_deltas.get("blue", 0),
                )

            else:
                team_red = [p for p in players_info if p["team"] == "red"]
                team_blue = [p for p in players_info if p["team"] == "blue"]

                match_id = await connection.fetchval(
                    """
                    INSERT INTO matches_2v2
                        (player_red_1, player_red_2,
                         player_blue_1, player_blue_2,
                         score_red, score_blue,
                         elo_delta_red_1, elo_delta_red_2,
                         elo_delta_blue_1, elo_delta_blue_2)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                    RETURNING id
                    """,
                    player_ids[team_red[0]["username"]],
                    player_ids[team_red[1]["username"]],
                    player_ids[team_blue[0]["username"]],
                    player_ids[team_blue[1]["username"]],
                    score["red"],
                    score["blue"],
                    elo_deltas.get("red_1", 0),
                    elo_deltas.get("red_2", 0),
                    elo_deltas.get("blue_1", 0),
                    elo_deltas.get("blue_2", 0),
                )

            # Insert stats
            table_stats = "match_player_stats_2v2" if is_2v2 else "match_player_stats_1v1"
            for p in players_info:
                await connection.execute( # no return value win_proba, just execute the command
                    f"""
                    INSERT INTO {table_stats}
                        (match_id, player_id, role,
                         goals_scored, shots_total, shots_on_target,
                         saves, possession_pct, max_ball_speed, heatmap)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                    """,
                    match_id,
                    player_ids[p["username"]],
                    p["role"],
                    p["goals_scored"],
                    p["shots_total"],
                    p["shots_on_target"],
                    p["saves"],
                    p["possession_pct"],
                    p["max_ball_speed"],
                    json.dumps(p["heatmap"]) if p.get("heatmap") else None,
                )

            # Update ELO ratings of the players
            if not is_2v2:
                # 1v1
                await connection.execute(
                    "UPDATE players SET elo = elo + $1 WHERE id = $2",
                    elo_deltas.get("red", 0),
                    player_ids[red_player["username"]],
                )
                await connection.execute(
                    "UPDATE players SET elo = elo + $1 WHERE id = $2",
                    elo_deltas.get("blue", 0),
                    player_ids[blue_player["username"]],
                )
            else:
                # 2v2
                for key, p in zip(["red_1","red_2","blue_1","blue_2"], players_info): #TODO : doit etre dans l'ordre ?  
                    delta = elo_deltas.get(key, 0)
                    await connection.execute(
                        "UPDATE players SET elo = elo + $1 WHERE id = $2",
                        delta,
                        player_ids[p["username"]],
                    )

    print(f"[DB] Match {match_id} saved successfully")

# depends on teams composition. In 2v2, the gain is split equally among teammates 
def compute_elo_deltas(players_red: list, players_blue: list, score_red: int, score_blue: int):
    K = 32

    average_elo_red = sum(players_red)/len(players_red)
    average_elo_blue = sum(players_blue)/len(players_blue)

    win_proba_red  = 1 / (1 + 10 ** ((average_elo_blue - average_elo_red) / 400))
    win_proba_blue = 1 - win_proba_red

    if score_red > score_blue:
        actual_red, actual_blue = 1.0, 0.0
    elif score_blue > score_red:
        actual_red, actual_blue = 0.0, 1.0
    else:
        actual_red, actual_blue = 0.5, 0.5

    delta_red  = round(K * (actual_red  - win_proba_red))
    delta_blue = round(K * (actual_blue - win_proba_blue))

    # during team matches, we split the delta equally among the team members
    if len(players_red) > 1:
        delta_red_1 = delta_red_2 = delta_red // len(players_red)
        delta_blue_1 = delta_blue_2 = delta_blue // len(players_blue)
        return {
            "red_1": delta_red_1,
            "red_2": delta_red_2,
            "blue_1": delta_blue_1,
            "blue_2": delta_blue_2,
        }
    else:
        return {"red": delta_red, "blue": delta_blue}