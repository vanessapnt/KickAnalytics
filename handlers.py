import asyncio, json, base64, math, time, concurrent.futures
import numpy as np
import cv2
from aiohttp import web, WSMsgType

_inference_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix='onnx')

from config import *
from game import game, apply_homography, check_goal, store_pending_calibration, confirm_calibration
from vision import detect_ball, detect_field_corners
from db import save_match, compute_elo_deltas, get_pool
from zones import compute_attributed_stats
import state
from auth_session import get_session_user_from_request

async def broadcast(targets, msg):
    data = json.dumps(msg)
    await asyncio.gather(
        *[ws.send_str(data) for ws in targets.copy() if not ws.closed],
        return_exceptions=True
    )

def decode_base64_to_cv2(image_b64):
    img_bytes = base64.b64decode(image_b64.split(',')[1])
    img_array = np.frombuffer(img_bytes, dtype=np.uint8)
    return cv2.imdecode(img_array, cv2.IMREAD_COLOR)

def compute_stats():
    if len(state.ball_history) < 2:
        return {}
    # Convert canvas pixels to real-world centimeters, then speed to km/h.
    x_cm_per_px = FIELD_W / CANVAS_W
    y_cm_per_px = (FIELD_H + 2 * GOAL_DEPTH_CM) / CANVAS_H
    speeds, max_speed = [], 0
    for i in range(1, len(state.ball_history)):
        p1, p2 = state.ball_history[i-1], state.ball_history[i]
        dx, dy = p2["x"]-p1["x"], p2["y"]-p1["y"]
        dt = max((p2["t"]-p1["t"])/1000, 0.001)
        dx_cm = dx * x_cm_per_px
        dy_cm = dy * y_cm_per_px
        speed_cm_s = math.sqrt(dx_cm*dx_cm + dy_cm*dy_cm) / dt
        speed = speed_cm_s * 0.036
        speeds.append(speed)
        if speed > max_speed:
            max_speed = speed
    return {
        "avg_speed": sum(speeds)/len(speeds),
        "max_speed": max_speed,
    }

async def save_match_end(score: dict, stats: dict):
    red_users = state.current_match.get("red", [])
    blue_users = state.current_match.get("blue", [])
    match_mode = state.current_match.get("mode", "1v1")
    p_roles = state.current_match.get("roles", {"red": [], "blue": []})

    if not red_users or not blue_users:
        print("[DB] Players not defined, match not saved"); return

    pool = get_pool()
    if pool is None:
        print("[DB] Pool not initialized, match not saved"); return

    async with pool.acquire() as conn:
        elos_red = [await conn.fetchval("SELECT elo FROM players WHERE username=$1", u) for u in red_users]
        elos_blue = [await conn.fetchval("SELECT elo FROM players WHERE username=$1", u) for u in blue_users]

    if any(e is None for e in elos_red + elos_blue):
        print("[DB] Player not found, match not saved"); return

    elo_deltas = compute_elo_deltas(elos_red, elos_blue, score["red"], score["blue"])
    is_2v2 = match_mode == "2v2"

    attributed, (blue_poss, red_poss) = compute_attributed_stats(
        state.ball_history, state.goal_events, match_mode
    )

    def _pstat(team, role, key):
        r = "solo" if not is_2v2 else role
        return attributed.get((team, r), {}).get(key, 0)

    if not is_2v2:
        players_info = [
            {"username": red_users[0], "team": "red", "role": "solo",
             "goals_scored":    _pstat("red",  "solo", "goals"),
             "shots_total":     _pstat("red",  "solo", "shots_total"),
             "shots_on_target": _pstat("red",  "solo", "shots_on_target"),
             "saves":           _pstat("red",  "solo", "saves"),
             "possession_pct":  red_poss,
             "max_ball_speed":  stats.get("max_speed", 0)},
            {"username": blue_users[0], "team": "blue", "role": "solo",
             "goals_scored":    _pstat("blue", "solo", "goals"),
             "shots_total":     _pstat("blue", "solo", "shots_total"),
             "shots_on_target": _pstat("blue", "solo", "shots_on_target"),
             "saves":           _pstat("blue", "solo", "saves"),
             "possession_pct":  blue_poss,
             "max_ball_speed":  stats.get("max_speed", 0)},
        ]
        elo_broadcast = {
            "mode": "1v1",
            "red": [{"username": red_users[0], "delta": elo_deltas["red"]}],
            "blue": [{"username": blue_users[0], "delta": elo_deltas["blue"]}],
        }
    else:
        red_roles, blue_roles = p_roles.get("red", ["attacker","defender"]), p_roles.get("blue", ["attacker","defender"])
        players_info = []
        for u, role in zip(red_users, red_roles):
            players_info.append({"username": u, "team": "red", "role": role,
                "goals_scored":    _pstat("red",  role, "goals"),
                "shots_total":     _pstat("red",  role, "shots_total"),
                "shots_on_target": _pstat("red",  role, "shots_on_target"),
                "saves":           _pstat("red",  role, "saves"),
                "possession_pct":  red_poss,
                "max_ball_speed":  stats.get("max_speed", 0)})
        for u, role in zip(blue_users, blue_roles):
            players_info.append({"username": u, "team": "blue", "role": role,
                "goals_scored":    _pstat("blue", role, "goals"),
                "shots_total":     _pstat("blue", role, "shots_total"),
                "shots_on_target": _pstat("blue", role, "shots_on_target"),
                "saves":           _pstat("blue", role, "saves"),
                "possession_pct":  blue_poss,
                "max_ball_speed":  stats.get("max_speed", 0)})
        elo_broadcast = {
            "mode": "2v2",
            "red":  [{"username": red_users[0], "delta": elo_deltas.get("red_1", 0)},
                     {"username": red_users[1], "delta": elo_deltas.get("red_2", 0)}],
            "blue": [{"username": blue_users[0], "delta": elo_deltas.get("blue_1", 0)},
                     {"username": blue_users[1], "delta": elo_deltas.get("blue_2", 0)}],
        }

    await save_match(players_info, score, elo_deltas)

    async with pool.acquire() as conn:
        new_elos = {u: await conn.fetchval("SELECT elo FROM players WHERE username=$1", u)
                    for u in red_users + blue_users}

    elo_update_msg = {"type": "elo_update", **elo_broadcast, "new_elos": new_elos}
    await broadcast(state.spectators, elo_update_msg)
    await broadcast(state.controllers, elo_update_msg)
    if state.matchmaking_room:
        for p in state.matchmaking_room["players"]:
            try: await p["ws"].send_str(json.dumps(elo_update_msg))
            except: pass

    await handle_camera_end()

async def inference_worker():
    loop = asyncio.get_event_loop()
    while True:
        frame, ts, image_b64, orig_w, orig_h = await state.frame_queue.get()
        if state.match_over:
            state.frame_queue.task_done(); continue

        state.frame_replay_buffer.append({"image": image_b64, "ts": ts})
        if len(state.frame_replay_buffer) > state.REPLAY_BUFFER_SIZE:
            state.frame_replay_buffer.pop(0)

        if orig_w is None or orig_h is None:
            orig_h, orig_w = frame.shape[:2]

        cx, cy, _ = await loop.run_in_executor(_inference_executor, detect_ball, frame)

        if cx is not None:
            cx = cx / 640 * orig_w
            cy = cy / 640 * orig_h
            kx, ky = apply_homography(cx, cy)
            if kx is None:
                state.frame_queue.task_done(); continue

            state.ball_history.append({"x": kx, "y": ky, "t": ts})
            scorer = check_goal(kx, ky)

            if scorer and not state.replay_in_progress:
                game.score[scorer] += 1
                state.goal_events.append({"team": scorer, "ts": ts})
                await broadcast(state.spectators, {"type": "goal", "team": scorer, "score": dict(game.score)})
                await broadcast(state.controllers, {"type": "goal", "team": scorer, "score": dict(game.score)})
                asyncio.create_task(send_replay_around_goal(ts, 10, 10))

                if game.score[scorer] >= state.GOALS_TO_WIN:
                    state.match_over = True
                    stats = compute_stats()
                    await broadcast(state.spectators, {"type": "match_end", "score": dict(game.score), "stats": stats})
                    await broadcast(state.controllers, {"type": "match_end", "score": dict(game.score), "stats": stats})
                    asyncio.create_task(save_match_end(dict(game.score), stats))

            await broadcast(state.spectators, {
                "type": "position",
                "x": kx / CANVAS_W,
                "y": (ky - GOAL_DEPTH_PX) / FIELD_H_PX,
                "ts": ts, "score": dict(game.score),
            })

        state.frame_queue.task_done()

def _find_goal_frame_index(buffer, goal_ts):
    if not buffer:
        return None
    if goal_ts is None:
        return len(buffer) - 1
    best_idx = None
    best_dist = None
    for i, item in enumerate(buffer):
        ts = item.get("ts")
        if ts is None:
            continue
        dist = abs(ts - goal_ts)
        if best_dist is None or dist < best_dist:
            best_dist = dist
            best_idx = i
    return best_idx if best_idx is not None else len(buffer) - 1

async def send_replay_around_goal(goal_ts, n_before, n_after):
    state.replay_in_progress = True
    deadline = time.time() + 2.0
    while True:
        buffer = list(state.frame_replay_buffer)
        goal_idx = _find_goal_frame_index(buffer, goal_ts)
        if goal_idx is None:
            break
        after_count = len(buffer) - goal_idx - 1
        if after_count >= n_after or time.time() >= deadline:
            start = max(0, goal_idx - n_before)
            end = min(len(buffer), goal_idx + n_after + 1)
            replay_frames = [item["image"] for item in buffer[start:end]]
            if replay_frames:
                await broadcast(state.spectators, {"type": "replay", "frames": replay_frames})
                await asyncio.sleep(len(replay_frames) * 0.08 + 0.5)
            break
        await asyncio.sleep(0.03)
    state.replay_in_progress = False

async def process_camera_message(ws, msg):
    data = json.loads(msg)
    msg_type = data.get("type")
    loop = asyncio.get_event_loop()

    if msg_type == "frame":
        if state.frame_queue.full():
            return
        image_b64 = data["image"]
        ts = data.get("ts") or int(time.time() * 1000)
        orig_w = data.get("frame_width")
        orig_h = data.get("frame_height")
        frame = await loop.run_in_executor(None, decode_base64_to_cv2, image_b64)
        if frame is not None:
            await state.frame_queue.put((frame, ts, image_b64, orig_w, orig_h))

    elif msg_type == "calibration_frame":
        image_b64 = data.get("image")
        frame = await loop.run_in_executor(None, decode_base64_to_cv2, image_b64)
        if frame is None:
            await broadcast(state.cameras, {"type": "calibration_failed"})
            await broadcast(state.controllers, {"type": "calibration_failed", "image": image_b64})
            await broadcast(state.spectators, {"type": "calibration_failed"})
            return
        corners = await loop.run_in_executor(None, detect_field_corners, frame)
        if corners is None:
            await broadcast(state.cameras, {"type": "calibration_failed"})
            await broadcast(state.controllers, {"type": "calibration_failed", "image": image_b64})
            await broadcast(state.spectators, {"type": "calibration_failed"})
            return
        store_pending_calibration(corners, data.get("frame_width", frame.shape[1]), data.get("frame_height", frame.shape[0]))
        await broadcast(state.cameras, {"type": "calibration_preview", "corners": corners})

    elif msg_type == "calibration_preview":
        store_pending_calibration(data["corners"], data.get("frame_width", 0), data.get("frame_height", 0))
        await broadcast(state.controllers, {"type": "calibration_preview", "image": data["image"], "corners": data["corners"]})

    elif msg_type == "calibration_failed":
        await broadcast(state.controllers, {"type": "calibration_failed"})
        await broadcast(state.spectators, {"type": "calibration_failed"})

async def handle_camera(request):
    from matchmaking import camera_joined, camera_left

    session_user = get_session_user_from_request(request)
    if not session_user:
        return web.json_response({"error": "Unauthorized"}, status=401)

    username = (session_user.get("username") or "inconnu").strip().lower()

    # Allow the currently validated camera, and also allow a matchmaking player
    # to connect during active camera phases so camera_joined can auto-validate.
    is_validated_camera = (state.validated_camera_username == username)
    is_matchmaking_player = (
        state.matchmaking_room and
        any(p["username"] == username for p in state.matchmaking_room.get("players", []))
    )
    active_camera_phase = state.table_state in ("waiting_camera", "calibrating", "playing")

    if active_camera_phase and not (is_validated_camera or is_matchmaking_player):
        return web.json_response({"error": "Not allowed camera for this match"}, status=403)

    # no new in Python, just call the constructor to create the server ws
    ws = web.WebSocketResponse(max_msg_size=10*1024*1024)
    # sends 101 OK UPGRADE http -> ws
    await ws.prepare(request)

    state.cameras.add(ws) # WebSocketResponse object

    display_name = (session_user.get("display_name") or username).strip() or username
    await camera_joined(ws, username, display_name)

    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                data = json.loads(msg.data)
                msg_type = data.get("type")

                if msg_type in ("frame", "calibration_frame", "calibration_preview", "calibration_failed"):
                    await process_camera_message(ws, msg.data)

            elif msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                break
    finally:
        state.cameras.discard(ws)
        await camera_left(ws)
    return ws

async def handle_controller(request):
    session_user = get_session_user_from_request(request)
    if not session_user:
        return web.json_response({"error": "Unauthorized"}, status=401)

    username = (session_user.get("username") or "").strip().lower()
    display_name = (session_user.get("display_name") or username).strip() or username

    # Keep controller WS alive through idle phases (no user input during match).
    ws = web.WebSocketResponse(heartbeat=20) # every 20 sec
    await ws.prepare(request)
    state.controllers.add(ws)

    if username:
        state.ws_players[ws] = {"username": username, "display_name": display_name, "elo": 1000}
        if state.matchmaking_room:
            for player in state.matchmaking_room["players"]:
                if player["username"] == username and player["ws"] is None:
                    player["ws"] = ws
                    break

    from matchmaking import table_status_payload
    await ws.send_str(json.dumps(table_status_payload()))
    cam_ws = state.validated_camera_ws
    cam_username = state.validated_camera_username
    if cam_username and (cam_ws is None or cam_ws.closed):
        await ws.send_str(json.dumps({
            "type": "camera_selected",
            "camera": {"username": cam_username, "display_name": cam_username},
        }))
    elif cam_ws and not cam_ws.closed:
        cam_info = state.camera_pool.get(cam_ws, {})
        await ws.send_str(json.dumps({
            "type": "camera_selected",
            "camera": {
                "username": cam_username or cam_info.get("username", ""),
                "display_name": cam_info.get("display_name", ""),
            }
        }))
    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                data = json.loads(msg.data)
                msg_type = data.get("type")
                if msg_type == "trigger_calibration":
                    cam = state.validated_camera_ws
                    if cam is None or cam.closed:
                        cam = next((w for w in state.camera_pool if not w.closed), None)
                        if cam:
                            state.validated_camera_ws = cam
                            state.validated_camera_username = state.camera_pool[cam]["username"]
                    if cam and not cam.closed:
                        state.match_over = False
                        await cam.send_str(json.dumps({"type": "start_calibration"}))
                        print(f"[CTRL] start_calibration sent to {state.validated_camera_username}")
                    else:
                        print("[CTRL] trigger_calibration: no camera available")
                elif msg_type == "set_players":
                    state.current_match["mode"] = data.get("mode", "1v1")
                    state.current_match["red"] = data.get("red", [])
                    state.current_match["blue"] = data.get("blue", [])
                    state.current_match["roles"] = data.get("roles", {"red": [], "blue": []})
                    print(f"[MATCH] Mode={state.current_match['mode']} Red={state.current_match['red']} Blue={state.current_match['blue']}")
                elif msg_type == "force_end_match":
                    if not state.match_over:
                        from matchmaking import _force_end_match
                        await _force_end_match(keep_room=True)

                elif msg_type == "mm_leave_match":
                    from matchmaking import _mm_remove_player_by_username
                    await _mm_remove_player_by_username(username)
                    await ws.close()
                    continue

                elif msg_type == "confirm_calibration":
                    ok = confirm_calibration()
                    if ok:
                        state.match_over = False
                        state.match_paused = False
                        state.table_state = "playing"
                        state.ball_history.clear()
                        state.goal_events.clear()
                        state.frame_replay_buffer.clear()
                        game.score["red"] = 0
                        game.score["blue"] = 0
                        game.ball_in_goal = False
                        if state.validated_camera_ws and not state.validated_camera_ws.closed:
                            await state.validated_camera_ws.send_str(json.dumps({"type": "calibration_ok"}))
                        await broadcast(state.controllers, {"type": "calibration_ok"})
                        await broadcast(state.spectators, {"type": "calibration_ok"})
                    else:
                        await broadcast(state.controllers, {"type": "calibration_failed"})
            elif msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                break
    finally:
        state.controllers.discard(ws)

        from matchmaking import _force_end_match, _mm_remove_player_by_username

        player_info = state.ws_players.pop(ws, {})
        username = player_info.get("username", "")
        is_active_in_room = (
            state.matchmaking_room and
            any(p["username"] == username and p["ws"] is ws for p in state.matchmaking_room.get("players", []))
        )
        if is_active_in_room:
            if state.table_state in ("playing", "calibrating") and not state.match_over:
                print(f"[CTRL] Player {username} disconnected during match -> forcing end")
                await _force_end_match()
            else:
                print(f"[CTRL] Player {username} disconnected -> removing from room")
                await _mm_remove_player_by_username(username)

    return ws

async def handle_spectator(request):
    if not SPECTATOR_PUBLIC:
        session_user = get_session_user_from_request(request)
        if not session_user:
            return web.json_response({"error": "Unauthorized"}, status=401)

    ws = web.WebSocketResponse()
    await ws.prepare(request)
    state.spectators.add(ws)
    try:
        async for msg in ws:
            if msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                break
    finally:
        state.spectators.discard(ws)
    return ws

async def handle_camera_end():
    state.validated_camera_ws = None
    state.validated_camera_username = None
    from matchmaking import broadcast_table_status
    await broadcast_table_status()