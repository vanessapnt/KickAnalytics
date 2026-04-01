import asyncio, json, base64, math, time
import numpy as np
import cv2
from aiohttp import web, WSMsgType

from config import *
from game import game, apply_homography, check_goal, store_pending_calibration, confirm_calibration
from vision import detect_ball, detect_field_corners
from db import save_match, compute_elo_deltas, get_pool
import state

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
    speeds, heatmap, max_speed = [], np.zeros((20, 40)), 0
    best_shot = best_defense = None
    max_decel = 0
    for i in range(1, len(state.ball_history)):
        p1, p2 = state.ball_history[i-1], state.ball_history[i]
        dx, dy = p2["x"]-p1["x"], p2["y"]-p1["y"]
        dt = max((p2["t"]-p1["t"])/1000, 0.001)
        speed = math.sqrt(dx*dx + dy*dy) / dt
        speeds.append(speed)
        gx = int(p2["x"]/CANVAS_W*40)
        gy = int(p2["y"]/CANVAS_H*20)
        if 0 <= gx < 40 and 0 <= gy < 20:
            heatmap[gy][gx] += 1
        if speed > max_speed:
            max_speed = speed
            best_shot = p2
        if i > 1:
            decel = speeds[-2] - speed
            near_goal = p2["y"] < 0.1*CANVAS_H or p2["y"] > 0.9*CANVAS_H
            if near_goal and decel > max_decel:
                max_decel = decel
                best_defense = p2
    return {
        "avg_speed": sum(speeds)/len(speeds),
        "max_speed": max_speed,
        "best_shot": best_shot,
        "best_defense": best_defense,
        "heatmap": heatmap.tolist(),
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

    if not is_2v2:
        players_info = [
            {"username": red_users[0], "team": "red", "role": "solo",
             "goals_scored": score["red"], "shots_total": 0, "shots_on_target": 0,
             "saves": 0, "possession_pct": 0.0,
             "max_ball_speed": stats.get("max_speed", 0), "heatmap": stats.get("heatmap")},
            {"username": blue_users[0], "team": "blue", "role": "solo",
             "goals_scored": score["blue"], "shots_total": 0, "shots_on_target": 0,
             "saves": 0, "possession_pct": 0.0,
             "max_ball_speed": stats.get("max_speed", 0), "heatmap": stats.get("heatmap")},
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
                "goals_scored": score["red"], "shots_total": 0, "shots_on_target": 0,
                "saves": 0, "possession_pct": 0.0,
                "max_ball_speed": stats.get("max_speed", 0), "heatmap": stats.get("heatmap")})
        for u, role in zip(blue_users, blue_roles):
            players_info.append({"username": u, "team": "blue", "role": role,
                "goals_scored": score["blue"], "shots_total": 0, "shots_on_target": 0,
                "saves": 0, "possession_pct": 0.0,
                "max_ball_speed": stats.get("max_speed", 0), "heatmap": stats.get("heatmap")})
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

        state.frame_replay_buffer.append(image_b64)
        if len(state.frame_replay_buffer) > state.REPLAY_BUFFER_SIZE:
            state.frame_replay_buffer.pop(0)

        if orig_w is None or orig_h is None:
            orig_h, orig_w = frame.shape[:2]

        cx, cy, conf = await loop.run_in_executor(None, detect_ball, frame)

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
                replay_before = list(state.frame_replay_buffer)
                await broadcast(state.spectators, {"type": "goal", "team": scorer, "score": dict(game.score)})
                await broadcast(state.controllers, {"type": "goal", "team": scorer, "score": dict(game.score)})
                asyncio.create_task(send_replay_after(replay_before, 10))

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
                "conf": conf, "ts": ts, "score": dict(game.score),
            })

        state.frame_queue.task_done()

async def send_replay_after(before_frames, n_after):
    state.replay_in_progress = True
    target = len(state.frame_replay_buffer) + n_after
    while len(state.frame_replay_buffer) < min(target, state.REPLAY_BUFFER_SIZE):
        await asyncio.sleep(0.05)
    after_frames = state.frame_replay_buffer[-n_after:] if len(state.frame_replay_buffer) >= n_after else list(state.frame_replay_buffer)
    await broadcast(state.spectators, {"type": "replay", "frames": before_frames + after_frames})
    await asyncio.sleep(len(before_frames + after_frames) * 0.08 + 0.5)
    state.replay_in_progress = False

_frame_counter = 0

async def process_camera_message(ws, msg):
    global _frame_counter
    data = json.loads(msg)
    msg_type = data.get("type")
    loop = asyncio.get_event_loop()

    if msg_type == "frame":
        _frame_counter += 1
        if _frame_counter % 2 != 0:
            return
        image_b64 = data["image"]
        orig_w = data.get("frame_width")
        orig_h = data.get("frame_height")
        frame = await loop.run_in_executor(None, decode_base64_to_cv2, image_b64)
        if frame is not None and not state.frame_queue.full():
            await state.frame_queue.put((frame, data.get("ts"), image_b64, orig_w, orig_h))

    elif msg_type == "calibration_frame":
        frame = await loop.run_in_executor(None, decode_base64_to_cv2, data["image"])
        if frame is None:
            await broadcast(state.cameras, {"type": "calibration_failed"})
            await broadcast(state.controllers, {"type": "calibration_failed"})
            await broadcast(state.spectators, {"type": "calibration_failed"})
            return
        corners = await loop.run_in_executor(None, detect_field_corners, frame)
        if corners is None:
            await broadcast(state.cameras, {"type": "calibration_failed"})
            await broadcast(state.controllers, {"type": "calibration_failed"})
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

    ws = web.WebSocketResponse(max_msg_size=10*1024*1024)
    await ws.prepare(request)

    username = request.rel_url.query.get("username", "inconnu")
    display_name = request.rel_url.query.get("display_name", username)

    state.cameras.add(ws)
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
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    state.controllers.add(ws)
    from matchmaking import table_status_payload
    await ws.send_str(json.dumps(table_status_payload()))
    cam_ws = state.active_camera_ws
    cam_username = state.active_camera_username
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
                    cam = state.active_camera_ws
                    if cam is None or cam.closed:
                        cam = next((w for w in state.camera_pool if not w.closed), None)
                        if cam:
                            state.active_camera_ws = cam
                            state.active_camera_username = state.camera_pool[cam]["username"]
                    if cam and not cam.closed:
                        state.match_over = False
                        await cam.send_str(json.dumps({"type": "start_calibration"}))
                        print(f"[CTRL] start_calibration sent to {state.active_camera_username}")
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

                elif msg_type == "confirm_calibration":
                    ok = confirm_calibration()
                    if ok:
                        state.match_over = False
                        state.match_paused = False
                        state.table_state = "playing"
                        state.ball_history.clear()
                        state.frame_replay_buffer.clear()
                        game.score["red"] = 0
                        game.score["blue"] = 0
                        game.ball_in_goal = False
                        if state.active_camera_ws and not state.active_camera_ws.closed:
                            await state.active_camera_ws.send_str(json.dumps({"type": "calibration_ok"}))
                        await broadcast(state.controllers, {"type": "calibration_ok"})
                        await broadcast(state.spectators, {"type": "calibration_ok"})
                    else:
                        await broadcast(state.controllers, {"type": "calibration_failed"})
            elif msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                break
    finally:
        state.controllers.discard(ws)
    return ws

async def handle_spectator(request):
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
    state.table_state = "idle"
    state.active_camera_username = None
    state.prevalidated_camera_username = None
    state.matchmaking_room = None
    from matchmaking import broadcast_table_status
    await broadcast_table_status()