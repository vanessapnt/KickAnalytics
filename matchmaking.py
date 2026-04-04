import asyncio, json
from aiohttp import web, WSMsgType

import state
from handlers import broadcast
from auth_session import get_session_user_from_request
from db import get_pool

def table_status_payload():
    room = None
    if state.matchmaking_room:
        room = {
            "mode": state.matchmaking_room["mode"],
            "players": [
                {"username": p["username"], "display_name": p["display_name"],
                 "elo": p["elo"], "ready": p["ready"]}
                for p in state.matchmaking_room["players"]
            ],
            "needed": 2 if state.matchmaking_room["mode"] == "1v1" else 4,
        }
    return {
        "type": "table_status",
        "state": state.table_state,
        "room": room,
        "camera_pool": list({
            v["username"]: {"username": v["username"], "display_name": v["display_name"]}
            for v in state.camera_pool.values()
        }.values()),
        "match_paused": state.match_paused,
    }

async def broadcast_table_status():
    payload = table_status_payload() # state at the moment for UI with the new camera
    await broadcast(state.spectators, payload)
    if state.matchmaking_room:
        for p in state.matchmaking_room["players"]:
            try:
                await p["ws"].send_str(json.dumps(payload))
            except Exception:
                pass

CAMERA_POOL_MAX = 3

async def camera_joined(ws, username, display_name):
    is_matchmaking_player = (
        state.matchmaking_room and
        any(p["username"] == username for p in state.matchmaking_room["players"])
    )
    if is_matchmaking_player and state.table_state in ("waiting_camera", "calibrating", "playing"):
        state.camera_pool[ws] = {"username": username, "display_name": display_name}
        state.validated_camera_ws = ws
        state.validated_camera_username = username
        state.table_state = "calibrating"
        await broadcast(state.controllers, {"type": "camera_selected",
                                            "camera": {"username": username, "display_name": display_name}})
        await broadcast_table_status()
        print(f"[CAM POOL] {display_name} player-camera -> auto validation")
        return

    if len(state.camera_pool) >= CAMERA_POOL_MAX:
        await ws.send_str(json.dumps({
            "type": "camera_pool_full",
            "error": f"Pool is full (max {CAMERA_POOL_MAX} cameras)"
        }))
        print(f"[CAM POOL] {display_name} rejected, pool is full")
        return

    state.camera_pool[ws] = {"username": username, "display_name": display_name}
    await broadcast_table_status()
    print(f"[CAM POOL] {display_name} joined the pool ({len(state.camera_pool)} cameras)")


async def _force_end_match(keep_room=False):
    """Force la fin du match proprement : reset état, broadcast, sauvegarde.
    keep_room=True : garde la matchmaking_room active (arrêt volontaire, rejouer possible).
    keep_room=False : détruit la room (déconnexion joueur).
    """
    from game import game
    from handlers import save_match_end, compute_stats
    import asyncio as _asyncio

    state.match_over = True
    state.validated_camera_ws = None
    state.validated_camera_username = None

    if keep_room and state.matchmaking_room:
        state.table_state = "waiting_camera"
    else:
        state.table_state = "free"
        state.matchmaking_room = None

    stats = compute_stats()
    score = dict(game.score)
    reason = "force_ended" if keep_room else "disconnected"
    await broadcast(state.spectators, {"type": "match_end", "score": score, "stats": stats, "reason": reason})
    await broadcast(state.controllers, {"type": "match_end", "score": score, "stats": stats, "reason": reason})
    _asyncio.create_task(save_match_end(score, stats))
    await broadcast_table_status()
    print(f"[MM] Match force-ended (keep_room={keep_room}), table -> {state.table_state}")

async def camera_left(ws):
    state.camera_pool.pop(ws, None)

    if ws is state.validated_camera_ws:
        state.validated_camera_ws = None
        if not state.match_over and state.table_state in ("playing", "calibrating"):
            print("[CAM POOL] Active camera disconnected -> forcing match end")
            await _force_end_match(keep_room=True)
        else:
            print("[CAM POOL] Active camera disconnected but match already over, ignoring")
        await broadcast_table_status()
        return

    await broadcast_table_status()


async def select_camera(controller_ws, camera_username):
    target_ws = next(
        (ws for ws, info in state.camera_pool.items()
         if info["username"] == camera_username),
        None
    )
    if target_ws is None:
        await controller_ws.send_str(json.dumps({
            "type": "error", "error": "Camera not found in pool"
        }))
        return

    info = state.camera_pool.get(target_ws) or {"username": camera_username, "display_name": camera_username}

    state.validated_camera_ws = target_ws
    state.validated_camera_username = info["username"]
    state.table_state = "calibrating"
    await target_ws.send_str(json.dumps({"type": "camera_validated"}))
    await broadcast(state.controllers, {"type": "camera_selected", "camera": info})
    print(f"[CAM POOL] {info['display_name']} validated as camera")

    await broadcast_table_status()

async def kick_camera(controller_ws, camera_username):
    target_ws = next(
        (ws for ws, info in state.camera_pool.items() if info["username"] == camera_username), None
    )
    if target_ws is None:
        await controller_ws.send_str(json.dumps({"type": "error", "error": "Camera not found"}))
        return
    display = state.camera_pool[target_ws]["display_name"]
    await target_ws.send_str(json.dumps({"type": "camera_kicked"}))
    await target_ws.close()
    print(f"[CAM POOL] {display} kicked")

async def _mm_remove_player(ws):
    state.ws_players.pop(ws, None)
    if not state.matchmaking_room:
        return
    before = len(state.matchmaking_room["players"])
    state.matchmaking_room["players"] = [
        p for p in state.matchmaking_room["players"] if p["ws"] is not ws
    ]
    if len(state.matchmaking_room["players"]) == 0:
        state.matchmaking_room = None
        state.table_state = "free"
    changed = (len(state.matchmaking_room["players"]) != before) if state.matchmaking_room else (before > 0)
    if changed:
        await broadcast_table_status()

async def _mm_start_match():
    players = state.matchmaking_room["players"]
    mode = state.matchmaking_room["mode"]

    if mode == "1v1":
        red_players, blue_players = [players[0]], [players[1]]
    else:
        red_players, blue_players = players[:2], players[2:]

    state.current_match["mode"] = mode
    state.current_match["red"] = [p["username"] for p in red_players]
    state.current_match["blue"] = [p["username"] for p in blue_players]
    state.current_match["roles"] = {
        "red": ["solo"] if mode == "1v1" else ["attacker", "defender"],
        "blue": ["solo"] if mode == "1v1" else ["attacker", "defender"],
    }
    state.table_state = "waiting_camera"

    for p in players:
        try:
            await p["ws"].send_str(json.dumps({
                "type": "mm_start",
                "role": "controller",
                "match": {
                    "mode": mode,
                    "red": [{"username": rp["username"], "display_name": rp["display_name"]} for rp in red_players],
                    "blue": [{"username": bp["username"], "display_name": bp["display_name"]} for bp in blue_players],
                }
            }))
        except Exception:
            pass

    await broadcast_table_status()

async def handle_lobby(request):
    session_user = get_session_user_from_request(request)
    if not session_user:
        return web.json_response({"error": "Unauthorized"}, status=401)

    username = (session_user.get("username") or "").strip().lower()
    display_name = (session_user.get("display_name") or username).strip() or username

    ws = web.WebSocketResponse()
    await ws.prepare(request)
    state.spectators.add(ws)
    if username:
        state.ws_players[ws] = {"username": username, "display_name": display_name, "elo": 1000}
    await ws.send_str(json.dumps(table_status_payload()))
    try:
        async for raw in ws:
            if raw.type == WSMsgType.TEXT:
                data = json.loads(raw.data)
                msg_type = data.get("type")

                if msg_type == "mm_join":
                    mode = data.get("mode", "1v1")

                    if not username:
                        await ws.send_str(json.dumps({"type": "mm_error", "error": "Authentication required"}))
                        continue

                    elo = 1000
                    pool = get_pool()
                    if pool is not None:
                        async with pool.acquire() as conn:
                            row = await conn.fetchrow(
                                "SELECT display_name, elo FROM players WHERE username=$1",
                                username,
                            )
                        if row is None:
                            await ws.send_str(json.dumps({"type": "mm_error", "error": "Player not found"}))
                            continue
                        display_name = row["display_name"]
                        elo = row["elo"]

                    if state.matchmaking_room and any(
                        p["username"] == username and p["ws"] is not ws
                        for p in state.matchmaking_room["players"]
                    ):
                        await ws.send_str(json.dumps({"type": "mm_error", "error": "You are already in the room"}))
                        continue
                    if state.matchmaking_room:
                        state.matchmaking_room["players"] = [
                            p for p in state.matchmaking_room["players"]
                            if not (p["username"] == username and p["ws"] is not ws)
                        ]

                    if state.table_state == "free":
                        state.matchmaking_room = {"mode": mode, "players": []}
                        state.table_state = "matchmaking"
                    elif state.table_state != "matchmaking":
                        await ws.send_str(json.dumps({"type": "mm_error", "error": "Table is busy"}))
                        continue

                    if not state.matchmaking_room:
                        await ws.send_str(json.dumps({"type": "mm_error", "error": "Table is busy"}))
                        continue
                    needed = 2 if state.matchmaking_room["mode"] == "1v1" else 4
                    if len(state.matchmaking_room["players"]) >= needed:
                        await ws.send_str(json.dumps({"type": "mm_error", "error": "Room is full"}))
                        continue

                    state.matchmaking_room["players"].append({
                        "username": username, "display_name": display_name,
                        "elo": elo, "ready": False, "ws": ws,
                    })
                    state.ws_players[ws] = {"username": username, "display_name": display_name, "elo": elo}
                    await broadcast_table_status()

                elif msg_type == "mm_become_controller":
                    if state.matchmaking_room:
                        for p in state.matchmaking_room["players"]:
                            if p["ws"] is ws:
                                p["ws"] = None
                                break
                    state.ws_players.pop(ws, None)
                    print(f"[MM] Player detached WS to become controller")

                elif msg_type == "mm_leave":
                    await _mm_remove_player(ws)

                elif msg_type == "mm_ready":
                    if not state.matchmaking_room:
                        continue
                    for p in state.matchmaking_room["players"]:
                        if p["ws"] is ws:
                            p["ready"] = True
                            break
                    needed = 2 if state.matchmaking_room["mode"] == "1v1" else 4
                    all_in = len(state.matchmaking_room["players"]) == needed
                    all_rdy = all(p["ready"] for p in state.matchmaking_room["players"])
                    if all_in and all_rdy:
                        await _mm_start_match()
                    else:
                        await broadcast_table_status()

                elif msg_type == "select_camera":
                    await select_camera(ws, data.get("username", ""))

                elif msg_type == "kick_camera":
                    await kick_camera(ws, data.get("username", ""))

                elif msg_type == "lobby_film":
                    if username:
                        state.cameras.add(ws)
                        await camera_joined(ws, username, display_name)

                elif msg_type == "lobby_stop_film":
                    state.cameras.discard(ws)
                    await camera_left(ws)

            elif raw.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                break
    finally:
        state.spectators.discard(ws)
        player_info = state.ws_players.pop(ws, {})
        username = player_info.get("username", "")
        is_active_in_room = (
            state.matchmaking_room and
            any(p["username"] == username and p["ws"] is ws for p in state.matchmaking_room.get("players", []))
        )
        if is_active_in_room:
            if state.table_state in ("playing", "calibrating", "waiting_camera") and not state.match_over:
                print(f"[MM] Player {username} disconnected during match -> forcing end")
                await _force_end_match()
            else:
                print(f"[MM] Player {username} disconnected -> removing from room")
                await _mm_remove_player(ws)
        else:
            print(f"[MM] Player {username} WS closed (already detached or not in room, ignoring)")
    return ws