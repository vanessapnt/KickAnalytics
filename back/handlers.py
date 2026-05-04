import asyncio, json, base64, math, time, concurrent.futures
import numpy as np
import cv2
from aiohttp import web, WSMsgType

_inference_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix='onnx')

from config import *
from game import game, apply_homography, check_goal, store_pending_calibration, confirm_calibration
from vision import detect_ball, detect_field_corners
from db import save_match, compute_elo_deltas, get_pool
from zones import compute_attributed_stats, detect_contacts, last_scorer_contact, check_latest_contact
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
    return {"avg_speed": sum(speeds)/len(speeds), "max_speed": max_speed}

async def save_match_end(score: dict, stats: dict):
    red_users  = state.current_match.get("red", [])
    blue_users = state.current_match.get("blue", [])
    match_mode = state.current_match.get("mode", "1v1")
    p_roles    = state.current_match.get("roles", {"red": [], "blue": []})

    if not red_users or not blue_users:
        print("[DB] Players not defined, match not saved"); return

    pool = get_pool()
    if pool is None:
        print("[DB] Pool not initialized, match not saved"); return

    async with pool.acquire() as conn:
        elos_red  = [await conn.fetchval("SELECT elo FROM players WHERE username=$1", u) for u in red_users]
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
            {"username": red_users[0],  "team": "red",  "role": "solo",
             "goals_scored": _pstat("red",  "solo", "goals"),
             "shots_total":  _pstat("red",  "solo", "shots_total"),
             "shots_on_target": _pstat("red",  "solo", "shots_on_target"),
             "saves": _pstat("red",  "solo", "saves"),
             "possession_pct": red_poss,  "max_ball_speed": stats.get("max_speed", 0)},
            {"username": blue_users[0], "team": "blue", "role": "solo",
             "goals_scored": _pstat("blue", "solo", "goals"),
             "shots_total":  _pstat("blue", "solo", "shots_total"),
             "shots_on_target": _pstat("blue", "solo", "shots_on_target"),
             "saves": _pstat("blue", "solo", "saves"),
             "possession_pct": blue_poss, "max_ball_speed": stats.get("max_speed", 0)},
        ]
        elo_broadcast = {
            "mode": "1v1",
            "red":  [{"username": red_users[0],  "delta": elo_deltas["red"]}],
            "blue": [{"username": blue_users[0],  "delta": elo_deltas["blue"]}],
        }
    else:
        red_roles, blue_roles = p_roles.get("red", ["attacker","defender"]), p_roles.get("blue", ["attacker","defender"])
        players_info = []
        for u, role in zip(red_users, red_roles):
            players_info.append({"username": u, "team": "red", "role": role,
                "goals_scored": _pstat("red", role, "goals"),
                "shots_total":  _pstat("red", role, "shots_total"),
                "shots_on_target": _pstat("red", role, "shots_on_target"),
                "saves": _pstat("red", role, "saves"),
                "possession_pct": red_poss, "max_ball_speed": stats.get("max_speed", 0)})
        for u, role in zip(blue_users, blue_roles):
            players_info.append({"username": u, "team": "blue", "role": role,
                "goals_scored": _pstat("blue", role, "goals"),
                "shots_total":  _pstat("blue", role, "shots_total"),
                "shots_on_target": _pstat("blue", role, "shots_on_target"),
                "saves": _pstat("blue", role, "saves"),
                "possession_pct": blue_poss, "max_ball_speed": stats.get("max_speed", 0)})
        elo_broadcast = {
            "mode": "2v2",
            "red":  [{"username": red_users[0],  "delta": elo_deltas.get("red_1",  0)},
                     {"username": red_users[1],  "delta": elo_deltas.get("red_2",  0)}],
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

    state.table_state = "free"
    state.current_match = {"mode": "1v1", "red": [], "blue": [], "roles": {"red": [], "blue": []}}
    await broadcast(state.spectators, {"type": "table_status", "state": "free", "match": state.current_match})
    await broadcast(state.controllers, {"type": "table_status", "state": "free", "match": state.current_match})

async def _force_end_match():
    state.match_over = True
    state.table_state = "free"
    state.current_match = {"mode": "1v1", "red": [], "blue": [], "roles": {"red": [], "blue": []}}
    stats = compute_stats()
    score = dict(game.score)
    await broadcast(state.spectators, {"type": "match_end", "score": score, "stats": stats, "reason": "force_ended"})
    await broadcast(state.controllers, {"type": "match_end", "score": score, "stats": stats, "reason": "force_ended"})
    asyncio.create_task(save_match_end(score, stats))

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

            contact = check_latest_contact(state.ball_history)
            if contact:
                await broadcast(state.spectators, {
                    "type": "contact",
                    "team": contact["team"],
                    "rod":  contact["name"],
                    "x":    contact["x"] / CANVAS_W,
                    "y":    (contact["y"] - GOAL_DEPTH_PX) / FIELD_H_PX,
                    "deviation": contact["deviation"],
                    "t":    contact["t"],
                })

            scorer = check_goal(kx, ky)

            if scorer and not state.replay_in_progress:
                game.score[scorer] += 1
                state.goal_events.append({"team": scorer, "ts": ts})

                contacts_so_far = detect_contacts(state.ball_history)
                c_scorer = last_scorer_contact(contacts_so_far, ts, scorer)
                scorer_rod = c_scorer["name"] if c_scorer else None

                goal_msg = {"type": "goal", "team": scorer, "score": dict(game.score), "rod": scorer_rod}
                await broadcast(state.spectators, goal_msg)
                await broadcast(state.controllers, goal_msg)
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
    best_idx, best_dist = None, None
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
            end   = min(len(buffer), goal_idx + n_after + 1)
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
    session_user = get_session_user_from_request(request)
    if not session_user:
        return web.json_response({"error": "Unauthorized"}, status=401)

    username = (session_user.get("username") or "").strip().lower()
    if username not in ADMIN_USERNAMES:
        return web.json_response({"error": "Forbidden"}, status=403)

    ws = web.WebSocketResponse(heartbeat=20, max_msg_size=10*1024*1024)
    await ws.prepare(request)

    state.cameras.add(ws)
    state.camera_ws = ws
    print(f"[CAM] {username} connected")

    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                data = json.loads(msg.data)
                if data.get("type") in ("frame", "calibration_frame", "calibration_preview", "calibration_failed"):
                    await process_camera_message(ws, msg.data)
            elif msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                break
    finally:
        state.cameras.discard(ws)
        if state.camera_ws is ws:
            state.camera_ws = None
        if not state.match_over and state.table_state == "playing":
            await broadcast(state.spectators, {"type": "match_paused", "reason": "camera_disconnected"})
            await broadcast(state.controllers, {"type": "match_paused", "reason": "camera_disconnected"})
        print(f"[CAM] {username} disconnected")
    return ws

async def handle_controller(request):
    session_user = get_session_user_from_request(request)
    if not session_user:
        return web.json_response({"error": "Unauthorized"}, status=401)

    username = (session_user.get("username") or "").strip().lower()
    if state.table_state in ("calibrating", "playing"):
        authorized = state.current_match.get("red", []) + state.current_match.get("blue", [])
        if authorized and username not in authorized:
            return web.json_response({"error": "Table occupied by another match"}, status=403)

    ws = web.WebSocketResponse(heartbeat=20)
    await ws.prepare(request)
    state.controllers.add(ws)

    await ws.send_str(json.dumps({
        "type": "table_status",
        "state": state.table_state,
        "camera_connected": state.camera_ws is not None and not state.camera_ws.closed,
        "match": state.current_match,
        "score": dict(game.score),
    }))

    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                data = json.loads(msg.data)
                msg_type = data.get("type")

                if msg_type == "trigger_calibration":
                    cam = state.camera_ws
                    if cam and not cam.closed:
                        state.match_over = False
                        await cam.send_str(json.dumps({"type": "start_calibration"}))
                    else:
                        await ws.send_str(json.dumps({"type": "error", "error": "No camera connected"}))

                elif msg_type == "set_players":
                    state.current_match["mode"]  = data.get("mode", "1v1")
                    state.current_match["red"]   = data.get("red", [])
                    state.current_match["blue"]  = data.get("blue", [])
                    state.current_match["roles"] = data.get("roles", {"red": [], "blue": []})

                elif msg_type == "confirm_calibration":
                    ok = confirm_calibration()
                    if ok:
                        state.match_over = False
                        state.table_state = "playing"
                        state.ball_history.clear()
                        state.goal_events.clear()
                        state.frame_replay_buffer.clear()
                        game.score["red"] = 0
                        game.score["blue"] = 0
                        game.ball_in_goal = False
                        if state.camera_ws and not state.camera_ws.closed:
                            await state.camera_ws.send_str(json.dumps({"type": "calibration_ok"}))
                        await broadcast(state.controllers, {"type": "calibration_ok"})
                        await broadcast(state.spectators, {"type": "calibration_ok"})
                    else:
                        await broadcast(state.controllers, {"type": "calibration_failed"})

                elif msg_type == "force_end_match":
                    if not state.match_over:
                        await _force_end_match()

            elif msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                break
    finally:
        state.controllers.discard(ws)
    return ws

async def handle_spectator(request):
    if not SPECTATOR_PUBLIC:
        session_user = get_session_user_from_request(request)
        if not session_user:
            return web.json_response({"error": "Unauthorized"}, status=401)
    else:
        session_user = get_session_user_from_request(request)

    username = (session_user or {}).get("username", "").strip().lower()

    ws = web.WebSocketResponse(heartbeat=20)
    await ws.prepare(request)
    state.spectators.add(ws)
    if username:
        state.spectator_users[ws] = username

    await ws.send_str(json.dumps({
        "type": "table_status",
        "state": state.table_state,
        "match": state.current_match,
    }))

    # Push any pending invite immediately on connect
    if username:
        pool = get_pool()
        if pool:
            async with pool.acquire() as conn:
                invite = await conn.fetchrow(
                    """SELECT pm.id, pm.created_by, pm.red_players, pm.blue_players
                       FROM match_invites mi
                       JOIN pending_matches pm ON pm.id = mi.match_id
                       WHERE mi.username = $1 AND mi.status = 'pending' AND pm.status = 'pending'
                       ORDER BY pm.created_at DESC LIMIT 1""",
                    username
                )
            if invite:
                await ws.send_str(json.dumps({
                    "type": "match_invite",
                    "match_id": str(invite["id"]),
                    "created_by": invite["created_by"],
                    "red_players": list(invite["red_players"]),
                    "blue_players": list(invite["blue_players"]),
                }))

    try:
        async for msg in ws:
            if msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                break
    finally:
        state.spectators.discard(ws)
        state.spectator_users.pop(ws, None)
    return ws
