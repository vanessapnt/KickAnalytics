import json
import bcrypt
from aiohttp import web

import state
from db import get_pool
from auth_session import create_session_token, set_session_cookie, clear_session_cookie, get_session_user_from_request
from config import ENABLE_DEBUG_STATE_DUMP

def _resp(data, status=200):
    return web.Response(status=status, text=json.dumps(data), content_type="application/json")

def _safe_username_from_ws(ws):
    info = state.camera_pool.get(ws)
    if info:
        return info.get("username")
    player = state.ws_players.get(ws)
    if player:
        return player.get("username")
    return None

async def api_debug_dump_sets(request):
    if not ENABLE_DEBUG_STATE_DUMP:
        return _resp({"error": "Debug state dump is disabled"}, 403)

    session_user = get_session_user_from_request(request)
    if not session_user:
        return _resp({"error": "Unauthorized"}, 401)
    if session_user["username"] not in ADMIN_USERNAMES:
        return _resp({"error": "Forbidden"}, 403)

    cameras_usernames = sorted({u for u in (_safe_username_from_ws(ws) for ws in state.cameras) if u})
    spectators_usernames = sorted({u for u in (_safe_username_from_ws(ws) for ws in state.spectators) if u})
    controllers_usernames = sorted({u for u in (_safe_username_from_ws(ws) for ws in state.controllers) if u})
    camera_pool_usernames = sorted({info.get("username") for info in state.camera_pool.values() if info.get("username")})
    ws_players_usernames = sorted({info.get("username") for info in state.ws_players.values() if info.get("username")})

    payload = {
        "requested_by": (session_user.get("username") or "").strip().lower(),
        "table_state": state.table_state,
        "match_over": bool(state.match_over),
        "match_paused": bool(state.match_paused),
        "counts": {
            "cameras": len(state.cameras),
            "camera_pool": len(state.camera_pool),
            "controllers": len(state.controllers),
            "spectators": len(state.spectators),
            "ws_players": len(state.ws_players),
        },
        "camera": {
            "validated_camera_username": state.validated_camera_username,
            "validated_camera_ws_open": bool(state.validated_camera_ws and not state.validated_camera_ws.closed),
            "camera_pool_usernames": camera_pool_usernames,
            "cameras_usernames": cameras_usernames,
        },
        "controllers_usernames": controllers_usernames,
        "spectators_usernames": spectators_usernames,
        "ws_players_usernames": ws_players_usernames,
    }

    print("[DEBUG][STATE_DUMP]", json.dumps(payload, ensure_ascii=False))
    return _resp(payload)

async def api_auth_register(request):
    try:
        body = await request.json()
    except Exception:
        return _resp({"error": "Invalid JSON"}, 400)
    username = (body.get("username") or "").strip().lower()
    display_name = (body.get("display_name") or "").strip()
    password = (body.get("password") or "").strip()
    if not username or not display_name or not password:
        return _resp({"error": "username, display_name and password are required"}, 400)
    if len(password) < 6: # needs to be checked on server side too bc the front can be bypassed using curl
        return _resp({"error": "Password too short (minimum 6 characters)"}, 400)
    
    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    # encode() : str -> bytes (bcrypt needs bytes)
    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO players (username, display_name, password_hash) VALUES ($1, $2, $3) RETURNING id, username, display_name, elo",
                username, display_name, password_hash)
        response = _resp({"id": str(row["id"]), "username": row["username"], "display_name": row["display_name"], "elo": row["elo"]}, 201)
        token = create_session_token(user_id=str(row["id"]), username=row["username"], display_name=row["display_name"])
        # cookie "ka_session" = "eyJ1c2VybmFtZSI6ImFsaWNlIn0.ABC123signature" (payload in base64 + signature)
        # cookie_name = token 
        set_session_cookie(response, token, secure=(request.scheme == "https"))
        return response
    except Exception as e:
        if "unique" in str(e).lower():
            return _resp({"error": "This username is already taken"}, 409)
        return _resp({"error": str(e)}, 500)

async def api_auth_login(request):
    try:
        body = await request.json()
    except Exception:
        return _resp({"error": "Invalid JSON"}, 400)
    username = (body.get("username") or "").strip().lower()
    password = (body.get("password") or "").strip()
    if not username or not password:
        return _resp({"error": "username and password are required"}, 400)
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, username, display_name, elo, password_hash FROM players WHERE username = $1", username)
    if row is None:
        return _resp({"error": "Username not found"}, 401)
    if not bcrypt.checkpw(password.encode(), row["password_hash"].encode()):
        return _resp({"error": "Incorrect password"}, 401)
    response = _resp({"id": str(row["id"]), "username": row["username"], "display_name": row["display_name"], "elo": row["elo"]})
    token = create_session_token(user_id=str(row["id"]), username=row["username"], display_name=row["display_name"])
    set_session_cookie(response, token, secure=(request.scheme == "https"))
    return response

async def api_auth_logout(request):
    response = web.Response(status=204)
    clear_session_cookie(response, secure=(request.scheme == "https"))
    return response

async def api_leaderboard(request):
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT p.id, p.username, p.display_name, p.elo,
                # Nb of matches played (as red or blue) for this player
                COUNT(DISTINCT m.id) AS matches_played,
                # Nb of wins for this player
                COUNT(DISTINCT m.id) FILTER (
                    WHERE (m.player_red_id  = p.id AND m.score_red  > m.score_blue)
                       OR (m.player_blue_id = p.id AND m.score_blue > m.score_red)
                ) AS wins,
                # Winrate percentage (wins / matches_played)
                ROUND(100.0 * COUNT(DISTINCT m.id) FILTER (
                    WHERE (m.player_red_id  = p.id AND m.score_red  > m.score_blue)
                       OR (m.player_blue_id = p.id AND m.score_blue > m.score_red)
                ) / NULLIF(COUNT(DISTINCT m.id), 0), 1) AS winrate_pct,
                # Average possession percentage across all matches played by this player
                ROUND(AVG(s.possession_pct)::NUMERIC, 1) AS avg_possession,
                # Average shooting precision percentage across all matches played by this player (shots_on_target / shots_total * 100)
                ROUND(AVG(CASE WHEN s.shots_total > 0 THEN 100.0 * s.shots_on_target / s.shots_total END)::NUMERIC, 1) AS avg_precision_pct
            FROM players p
            LEFT JOIN matches_1v1 m ON p.id IN (m.player_red_id, m.player_blue_id)
            LEFT JOIN match_player_stats_1v1 s ON s.match_id = m.id AND s.player_id = p.id
            GROUP BY p.id ORDER BY p.elo DESC
        """)
        # player -> matches -> stats
        # TODO: leaderboard only for 1v1
    return _resp([{
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
            return _resp({"error": "Player not found"}, 404)
        pid = player["id"]
        # aggregate stats for this player across all 1v1 matches
        agg = await conn.fetchrow("""
            SELECT COUNT(DISTINCT m.id) AS matches_played,
                # Nb of wins
                COUNT(DISTINCT m.id) FILTER (
                    WHERE (m.player_red_id = $1 AND m.score_red > m.score_blue)
                       OR (m.player_blue_id = $1 AND m.score_blue > m.score_red)
                ) AS wins,
                # Winrate percentage (wins / matches_played)
                ROUND(100.0 * COUNT(DISTINCT m.id) FILTER (
                    WHERE (m.player_red_id = $1 AND m.score_red > m.score_blue)
                       OR (m.player_blue_id = $1 AND m.score_blue > m.score_red)
                ) / NULLIF(COUNT(DISTINCT m.id), 0), 1) AS winrate_pct,
                # Average possession percentage across all matches
                ROUND(AVG(s.possession_pct)::NUMERIC, 1) AS avg_possession,
                # Average shooting precision percentage (shots_on_target / shots_total * 100)
                ROUND(AVG(CASE WHEN s.shots_total > 0 THEN 100.0 * s.shots_on_target / s.shots_total END)::NUMERIC, 1) AS avg_precision_pct,
                # Total goals scored (0 if none)
                COALESCE(SUM(s.goals_scored), 0) AS total_goals,
                # Average max ball speed across all matches
                ROUND(AVG(s.max_ball_speed)::NUMERIC, 1) AS avg_max_speed
            FROM matches_1v1 m
            LEFT JOIN match_player_stats_1v1 s ON s.match_id = m.id AND s.player_id = $1
            WHERE m.player_red_id = $1 OR m.player_blue_id = $1
        """, pid)
        # last 10 1v1 matches
        m1 = await conn.fetch("""
            SELECT score_red, score_blue, played_at, player_red_id,
                CASE WHEN player_red_id = $1 THEN elo_delta_red ELSE elo_delta_blue END AS elo_delta
            FROM matches_1v1 WHERE player_red_id = $1 OR player_blue_id = $1
            ORDER BY played_at DESC LIMIT 10
        """, pid)
        # last 10 2v2 matches
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
        me, opp = (m["score_red"], m["score_blue"]) if is_red else (m["score_blue"], m["score_red"])
        recent.append({"mode": "1v1", "score_my_team": me, "score_opp": opp,
                       "won": me > opp, "draw": me == opp, "elo_delta": m["elo_delta"],
                       "date": m["played_at"].isoformat()})
    for m in m2:
        is_red = pid in (m["player_red_1"], m["player_red_2"])
        me, opp = (m["score_red"], m["score_blue"]) if is_red else (m["score_blue"], m["score_red"])
        recent.append({"mode": "2v2", "score_my_team": me, "score_opp": opp,
                       "won": me > opp, "draw": me == opp, "elo_delta": m["elo_delta"],
                       "date": m["played_at"].isoformat()})
    # merge 1v1 and 2v2 matches sorted by date desc
    recent.sort(key=lambda x: x["date"], reverse=True)

    return _resp({
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