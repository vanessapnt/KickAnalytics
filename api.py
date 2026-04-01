import json
import bcrypt
from aiohttp import web

from db import get_pool

def _json(data, status=200):
    return web.Response(status=status, text=json.dumps(data), content_type="application/json")

async def api_players(request):
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT username, display_name, elo FROM players ORDER BY elo DESC")
    return _json([{"username": r["username"], "display_name": r["display_name"], "elo": r["elo"]} for r in rows])

async def api_players_create(request):
    try:
        body = await request.json()
    except Exception:
        return _json({"error": "Invalid JSON"}, 400)
    username = (body.get("username") or "").strip()
    display_name = (body.get("display_name") or "").strip()
    if not username or not display_name:
        return _json({"error": "username and display_name are required"}, 400)
    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO players (username, display_name) VALUES ($1, $2) RETURNING id, username, display_name, elo",
                username, display_name)
        return _json({"id": str(row["id"]), "username": row["username"], "display_name": row["display_name"], "elo": row["elo"]}, 201)
    except Exception as e:
        if "unique" in str(e).lower():
            return _json({"error": "username already taken"}, 409)
        return _json({"error": str(e)}, 500)

async def api_auth_register(request):
    try:
        body = await request.json()
    except Exception:
        return _json({"error": "Invalid JSON"}, 400)
    username = (body.get("username") or "").strip().lower()
    display_name = (body.get("display_name") or "").strip()
    password = (body.get("password") or "").strip()
    if not username or not display_name or not password:
        return _json({"error": "username, display_name and password are required"}, 400)
    if len(password) < 6:
        return _json({"error": "Password too short (minimum 6 characters)"}, 400)
    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO players (username, display_name, password_hash) VALUES ($1, $2, $3) RETURNING id, username, display_name, elo",
                username, display_name, password_hash)
        return _json({"id": str(row["id"]), "username": row["username"], "display_name": row["display_name"], "elo": row["elo"]}, 201)
    except Exception as e:
        if "unique" in str(e).lower():
            return _json({"error": "This username is already taken"}, 409)
        return _json({"error": str(e)}, 500)

async def api_auth_login(request):
    try:
        body = await request.json()
    except Exception:
        return _json({"error": "Invalid JSON"}, 400)
    username = (body.get("username") or "").strip().lower()
    password = (body.get("password") or "").strip()
    if not username or not password:
        return _json({"error": "username and password are required"}, 400)
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, username, display_name, elo, password_hash FROM players WHERE username = $1", username)
    if row is None:
        return _json({"error": "Username not found"}, 401)
    if not bcrypt.checkpw(password.encode(), row["password_hash"].encode()):
        return _json({"error": "Incorrect password"}, 401)
    return _json({"id": str(row["id"]), "username": row["username"], "display_name": row["display_name"], "elo": row["elo"]})

async def api_leaderboard(request):
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT p.id, p.username, p.display_name, p.elo,
                COUNT(DISTINCT m.id) AS matches_played,
                COUNT(DISTINCT m.id) FILTER (
                    WHERE (m.player_red_id  = p.id AND m.score_red  > m.score_blue)
                       OR (m.player_blue_id = p.id AND m.score_blue > m.score_red)
                ) AS wins,
                ROUND(100.0 * COUNT(DISTINCT m.id) FILTER (
                    WHERE (m.player_red_id  = p.id AND m.score_red  > m.score_blue)
                       OR (m.player_blue_id = p.id AND m.score_blue > m.score_red)
                ) / NULLIF(COUNT(DISTINCT m.id), 0), 1) AS winrate_pct,
                ROUND(AVG(s.possession_pct)::NUMERIC, 1) AS avg_possession,
                ROUND(AVG(CASE WHEN s.shots_total > 0 THEN 100.0 * s.shots_on_target / s.shots_total END)::NUMERIC, 1) AS avg_precision_pct
            FROM players p
            LEFT JOIN matches_1v1 m ON p.id IN (m.player_red_id, m.player_blue_id)
            LEFT JOIN match_player_stats_1v1 s ON s.match_id = m.id AND s.player_id = p.id
            GROUP BY p.id ORDER BY p.elo DESC
        """)
    return _json([{
        "username": r["username"], "display_name": r["display_name"], "elo": r["elo"],
        "matches_played": r["matches_played"], "wins": r["wins"],
        "winrate_pct":       float(r["winrate_pct"])       if r["winrate_pct"]       is not None else None,
        "avg_possession":    float(r["avg_possession"])    if r["avg_possession"]    is not None else None,
        "avg_precision_pct": float(r["avg_precision_pct"]) if r["avg_precision_pct"] is not None else None,
    } for r in rows])

async def api_player_stats(request):
    username = request.match_info["username"].strip().lower()
    pool = get_pool()
    async with pool.acquire() as conn:
        player = await conn.fetchrow("SELECT id, username, display_name, elo FROM players WHERE username = $1", username)
        if player is None:
            return _json({"error": "Player not found"}, 404)
        pid = player["id"]
        agg = await conn.fetchrow("""
            SELECT COUNT(DISTINCT m.id) AS matches_played,
                COUNT(DISTINCT m.id) FILTER (
                    WHERE (m.player_red_id = $1 AND m.score_red > m.score_blue)
                       OR (m.player_blue_id = $1 AND m.score_blue > m.score_red)
                ) AS wins,
                ROUND(100.0 * COUNT(DISTINCT m.id) FILTER (
                    WHERE (m.player_red_id = $1 AND m.score_red > m.score_blue)
                       OR (m.player_blue_id = $1 AND m.score_blue > m.score_red)
                ) / NULLIF(COUNT(DISTINCT m.id), 0), 1) AS winrate_pct,
                ROUND(AVG(s.possession_pct)::NUMERIC, 1) AS avg_possession,
                ROUND(AVG(CASE WHEN s.shots_total > 0 THEN 100.0 * s.shots_on_target / s.shots_total END)::NUMERIC, 1) AS avg_precision_pct,
                COALESCE(SUM(s.goals_scored), 0) AS total_goals,
                ROUND(AVG(s.max_ball_speed)::NUMERIC, 1) AS avg_max_speed
            FROM matches_1v1 m
            LEFT JOIN match_player_stats_1v1 s ON s.match_id = m.id AND s.player_id = $1
            WHERE m.player_red_id = $1 OR m.player_blue_id = $1
        """, pid)
        m1 = await conn.fetch("""
            SELECT score_red, score_blue, played_at, player_red_id,
                CASE WHEN player_red_id = $1 THEN elo_delta_red ELSE elo_delta_blue END AS elo_delta
            FROM matches_1v1 WHERE player_red_id = $1 OR player_blue_id = $1
            ORDER BY played_at DESC LIMIT 10
        """, pid)
        m2 = await conn.fetch("""
            SELECT score_red, score_blue, played_at, player_red_1, player_red_2,
                CASE WHEN player_red_1 = $1 THEN elo_delta_red_1
                     WHEN player_red_2 = $1 THEN elo_delta_red_2
                     WHEN player_blue_1 = $1 THEN elo_delta_blue_1
                     ELSE elo_delta_blue_2 END AS elo_delta
            FROM matches_2v2
            WHERE $1 IN (player_red_1, player_red_2, player_blue_1, player_blue_2)
            ORDER BY played_at DESC LIMIT 10
        """, pid)

    recent = []
    for m in m1:
        is_red = m["player_red_id"] == pid
        my, opp = (m["score_red"], m["score_blue"]) if is_red else (m["score_blue"], m["score_red"])
        recent.append({"mode": "1v1", "score_my_team": my, "score_opp": opp,
                       "won": my > opp, "draw": my == opp, "elo_delta": m["elo_delta"],
                       "date": m["played_at"].isoformat()})
    for m in m2:
        is_red = pid in (m["player_red_1"], m["player_red_2"])
        my, opp = (m["score_red"], m["score_blue"]) if is_red else (m["score_blue"], m["score_red"])
        recent.append({"mode": "2v2", "score_my_team": my, "score_opp": opp,
                       "won": my > opp, "draw": my == opp, "elo_delta": m["elo_delta"],
                       "date": m["played_at"].isoformat()})
    recent.sort(key=lambda x: x["date"], reverse=True)

    return _json({
        "username": player["username"], "display_name": player["display_name"], "elo": player["elo"],
        "matches_played": agg["matches_played"] or 0,
        "wins": agg["wins"] or 0,
        "draws": 0,
        "winrate_pct": float(agg["winrate_pct"]) if agg["winrate_pct"] is not None else None,
        "avg_possession": float(agg["avg_possession"]) if agg["avg_possession"] is not None else None,
        "avg_precision_pct": float(agg["avg_precision_pct"]) if agg["avg_precision_pct"] is not None else None,
        "total_goals": int(agg["total_goals"]) if agg["total_goals"] is not None else 0,
        "avg_max_speed": float(agg["avg_max_speed"]) if agg["avg_max_speed"] is not None else None,
        "recent_matches": recent[:10],
    })