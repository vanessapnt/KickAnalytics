import asyncio, json
from aiohttp import web, WSMsgType

import state
from handlers import broadcast

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
        "camera_pool": [
            {"username": v["username"], "display_name": v["display_name"]}
            for v in state.camera_pool.values()
        ],
        "match_paused": state.match_paused,
    }

async def broadcast_table_status():
    payload = table_status_payload()
    await broadcast(state.spectators, payload)
    if state.matchmaking_room:
        for p in state.matchmaking_room["players"]:
            try:
                await p["ws"].send_str(json.dumps(payload))
            except Exception:
                pass

CAMERA_POOL_MAX = 3

async def camera_joined(ws, username, display_name):
    if state.match_paused and state.active_camera_username == username:
        state.camera_pool[ws] = {"username": username, "display_name": display_name}
        state.active_camera_ws = ws
        state.match_paused = False
        state.table_state = "playing"
        await ws.send_str(json.dumps({"type": "camera_validated"}))
        await ws.send_str(json.dumps({"type": "calibration_ok"}))
        await broadcast(state.controllers, {"type": "camera_resumed", "display_name": display_name})
        await broadcast(state.spectators, {"type": "camera_resumed"})
        await broadcast_table_status()
        print(f"[CAM POOL] {display_name} reconnected -> auto resume")
        return

    is_matchmaking_player = (
        state.matchmaking_room and
        any(p["username"] == username for p in state.matchmaking_room["players"])
    )
    if is_matchmaking_player and state.table_state in ("waiting_camera", "calibrating", "playing", "paused"):
        state.camera_pool[ws] = {"username": username, "display_name": display_name}
        state.active_camera_ws = ws
        state.active_camera_username = username
        state.match_paused = False
        state.table_state = "calibrating"
        await ws.send_str(json.dumps({"type": "camera_validated"}))
        await broadcast(state.controllers, {"type": "camera_selected",
                                            "camera": {"username": username, "display_name": display_name}})
        await broadcast_table_status()
        print(f"[CAM POOL] {display_name} player-camera -> auto validation")
        return

    if state.prevalidated_camera_username == username:
        state.prevalidated_camera_username = None
        state.camera_pool[ws] = {"username": username, "display_name": display_name}
        state.active_camera_ws = ws
        state.active_camera_username = username
        state.table_state = "calibrating"
        await ws.send_str(json.dumps({"type": "camera_validated"}))
        await broadcast(state.controllers, {"type": "camera_selected",
                                            "camera": {"username": username, "display_name": display_name}})
        await broadcast_table_status()
        print(f"[CAM POOL] {display_name} pre-validated -> direct validation")
        return

    if len(state.camera_pool) >= CAMERA_POOL_MAX:
        await ws.send_str(json.dumps({
            "type": "camera_pool_full",
            "error": f"Pool is full (max {CAMERA_POOL_MAX} cameras)"
        }))
        print(f"[CAM POOL] {display_name} rejected — pool is full")
        return

    state.camera_pool[ws] = {"username": username, "display_name": display_name}
    await broadcast_table_status()
    print(f"[CAM POOL] {display_name} joined the pool ({len(state.camera_pool)} cameras)")


async def camera_left(ws):
    state.camera_pool.pop(ws, None)

    if ws is state.active_camera_ws:
        state.active_camera_ws = None
        state.match_paused = True
        state.table_state = "paused"
        await broadcast(state.spectators, {"type": "match_paused"})
        await broadcast(state.controllers, {"type": "match_paused"})
        print("[CAM POOL] Active camera disconnected -> match paused")

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

    if state.match_paused:
        state.active_camera_ws = target_ws
        state.active_camera_username = info["username"]
        state.match_paused = False
        state.table_state = "calibrating"
        await target_ws.send_str(json.dumps({"type": "camera_validated"}))
        await broadcast(state.controllers, {"type": "camera_reselected", "camera": info})
        print(f"[CAM POOL] {info['display_name']} resumes the match")
    else:
        if target_ws in state.camera_pool:
            state.active_camera_ws = target_ws
            state.active_camera_username = info["username"]
            state.table_state = "calibrating"
            await target_ws.send_str(json.dumps({"type": "camera_validated"}))
            await broadcast(state.controllers, {"type": "camera_selected", "camera": info})
            print(f"[CAM POOL] {info['display_name']} validated as camera")
        else:
            state.prevalidated_camera_username = camera_username
            state.table_state = "calibrating"
            await target_ws.send_str(json.dumps({"type": "camera_validated"}))
            await broadcast(state.controllers, {"type": "camera_selected", "camera": info})
            print(f"[CAM POOL] {camera_username} pre-validated — waiting for camera.html")

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
    if not state.matchmaking_room:
        return
    before = len(state.matchmaking_room["players"])
    state.matchmaking_room["players"] = [
        p for p in state.matchmaking_room["players"] if p["ws"] is not ws
    ]
    if len(state.matchmaking_room["players"]) == 0:
        state.matchmaking_room = None
        if state.table_state == "waiting_camera":
            state.table_state = "idle"
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
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    state.spectators.add(ws)
    await ws.send_str(json.dumps(table_status_payload()))
    try:
        async for raw in ws:
            if raw.type == WSMsgType.TEXT:
                data = json.loads(raw.data)
                msg_type = data.get("type")

                if msg_type == "mm_join":
                    username = data.get("username", "").strip().lower()
                    display_name = data.get("display_name", "")
                    elo = data.get("elo", 1000)
                    mode = data.get("mode", "1v1")

                    if state.matchmaking_room and any(
                        p["username"] == username for p in state.matchmaking_room["players"]
                    ):
                        await ws.send_str(json.dumps({"type": "mm_error", "error": "You are already in the room"}))
                        continue

                    if state.table_state == "idle":
                        state.matchmaking_room = {"mode": mode, "players": []}
                        state.table_state = "matchmaking"
                    elif state.table_state != "matchmaking":
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
                    uname = data.get("username", "").strip() or state.ws_players.get(ws, {}).get("username", "")
                    dname = data.get("display_name", "") or state.ws_players.get(ws, {}).get("display_name", uname)
                    if uname:
                        state.cameras.add(ws)
                        await camera_joined(ws, uname, dname)

                elif msg_type == "lobby_stop_film":
                    state.cameras.discard(ws)
                    await camera_left(ws)

            elif raw.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                break
    finally:
        state.spectators.discard(ws)
        state.ws_players.pop(ws, None)
        if state.table_state in ("idle", "matchmaking"):
            await _mm_remove_player(ws)
    return ws