import asyncio, json, os, mimetypes
from aiohttp import web, WSMsgType
from pathlib import Path
import base64
import numpy as np
import cv2
import onnxruntime as ort
import math
import bcrypt

from config import *
from game import (
    game,
    apply_homography,
    kalman_update,
    check_goal,
    store_pending_calibration,
    confirm_calibration,
)
from db import init_db, close_db, save_match, compute_elo_deltas, get_pool

GOALS_TO_WIN       = 5
REPLAY_BUFFER_SIZE = 30

match_over          = False
ball_history        = []
frame_replay_buffer = []
replay_in_progress  = False

# ─────────────────────────────────────────────
# Table / Matchmaking state
# ─────────────────────────────────────────────
# table_state : 'idle' | 'matchmaking' | 'calibrating' | 'playing'
table_state = "idle"

# matchmaking_room = {
#   "mode": "1v1" | "2v2",
#   "players": [ { "username", "display_name", "elo", "ready": bool, "ws": ws } ]
# }
matchmaking_room = None

# ws → player info (pour tous les clients connectés au WS principal)
ws_players: dict = {}   # ws → { username, display_name, elo }

# Joueurs sélectionnés pour le match en cours (set par le controller avant calibration)
# mode  : '1v1' | '2v2'
# red   : [username]        (1v1) ou [username, username] (2v2)
# blue  : idem
# roles : { red: [role, ...], blue: [role, ...] }
current_match = {
    "mode":  "1v1",
    "red":   [],
    "blue":  [],
    "roles": {"red": [], "blue": []},
}

print("Loading ONNX model...")
sess       = ort.InferenceSession("model.onnx")
input_name = sess.get_inputs()[0].name
print("Model loaded ✓")

frame_queue: asyncio.Queue = None

cameras     = set()
controllers = set()
spectators  = set()

# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

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

# ─────────────────────────────────────────────
# Vision
# ─────────────────────────────────────────────

def detect_ball(frame):
    img = cv2.resize(frame, (640, 640))
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    img = img.astype(np.float32) / 255.0
    img = np.transpose(img, (2, 0, 1))
    img = np.expand_dims(img, 0)

    preds    = sess.run(None, {input_name: img})[0][0]
    best_idx = np.argmax(preds[4])
    conf     = float(preds[4][best_idx])

    if conf < 0.35:
        return None, None, conf

    return float(preds[0][best_idx]), float(preds[1][best_idx]), conf

def detect_field_corners(frame):
    hsv    = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask   = cv2.inRange(hsv, (35, 20, 40), (85, 255, 255))
    kernel = np.ones((15, 15), np.uint8)
    mask   = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    pts    = cv2.findNonZero(mask)
    if pts is None:
        return None
    hull   = cv2.convexHull(pts)
    approx = cv2.approxPolyDP(hull, 0.02 * cv2.arcLength(hull, True), True)
    if len(approx) != 4:
        print(f"[CALIB] approxPolyDP found {len(approx)} points, expected 4")
        return None
    pts4 = approx.reshape(4, 2)
    s    = pts4.sum(axis=1)
    d    = np.diff(pts4, axis=1).flatten()
    tl   = pts4[s.argmin()].tolist()
    br   = pts4[s.argmax()].tolist()
    tr   = pts4[d.argmin()].tolist()
    bl   = pts4[d.argmax()].tolist()
    print(f"[CALIB] corners: tl={tl} tr={tr} br={br} bl={bl}")
    return [tl, tr, br, bl]

# ─────────────────────────────────────────────
# Stats
# ─────────────────────────────────────────────

def compute_stats():
    if len(ball_history) < 2:
        return {}

    speeds       = []
    heatmap      = np.zeros((20, 40))
    max_speed    = 0
    best_shot    = None
    best_defense = None
    max_decel    = 0

    for i in range(1, len(ball_history)):
        p1 = ball_history[i - 1]
        p2 = ball_history[i]

        dx = p2["x"] - p1["x"]
        dy = p2["y"] - p1["y"]
        dt = max((p2["t"] - p1["t"]) / 1000, 0.001)

        speed = math.sqrt(dx * dx + dy * dy) / dt
        speeds.append(speed)

        gx = int(p2["x"] / CANVAS_W * 40)
        gy = int(p2["y"] / CANVAS_H * 20)
        if 0 <= gx < 40 and 0 <= gy < 20:
            heatmap[gy][gx] += 1

        if speed > max_speed:
            max_speed = speed
            best_shot = p2

        if i > 1:
            decel     = speeds[-2] - speed
            near_goal = p2["y"] < 0.1 * CANVAS_H or p2["y"] > 0.9 * CANVAS_H
            if near_goal and decel > max_decel:
                max_decel    = decel
                best_defense = p2

    return {
        "avg_speed":    sum(speeds) / len(speeds),
        "max_speed":    max_speed,
        "best_shot":    best_shot,
        "best_defense": best_defense,
        "heatmap":      heatmap.tolist(),
    }

# ─────────────────────────────────────────────
# DB save
# ─────────────────────────────────────────────

async def save_match_end(score: dict, stats: dict):
    red_users  = current_match.get("red",  [])
    blue_users = current_match.get("blue", [])
    match_mode = current_match.get("mode", "1v1")
    p_roles    = current_match.get("roles", {"red": [], "blue": []})

    if not red_users or not blue_users:
        print("[DB] Joueurs non définis, match non sauvegardé")
        return

    pool = get_pool()
    if pool is None:
        print("[DB] Pool non initialisé, match non sauvegardé")
        return

    # Récupère les ELOs depuis la DB
    async with pool.acquire() as conn:
        elos_red  = [await conn.fetchval("SELECT elo FROM players WHERE username=$1", u) for u in red_users]
        elos_blue = [await conn.fetchval("SELECT elo FROM players WHERE username=$1", u) for u in blue_users]

    if any(e is None for e in elos_red + elos_blue):
        print("[DB] Joueur introuvable en base, match non sauvegardé")
        return

    elo_deltas = compute_elo_deltas(elos_red, elos_blue, score["red"], score["blue"])

    is_2v2 = match_mode == "2v2"

    if not is_2v2:
        # 1v1 : rôle solo
        players_info = [
            {
                "username": red_users[0], "team": "red",  "role": "solo",
                "goals_scored": score["red"],  "shots_total": 0, "shots_on_target": 0,
                "saves": 0, "possession_pct": 0.0,
                "max_ball_speed": stats.get("max_speed", 0), "heatmap": stats.get("heatmap"),
            },
            {
                "username": blue_users[0], "team": "blue", "role": "solo",
                "goals_scored": score["blue"], "shots_total": 0, "shots_on_target": 0,
                "saves": 0, "possession_pct": 0.0,
                "max_ball_speed": stats.get("max_speed", 0), "heatmap": stats.get("heatmap"),
            },
        ]
        elo_broadcast = {
            "mode": "1v1",
            "red":  [{"username": red_users[0],  "delta": elo_deltas["red"]}],
            "blue": [{"username": blue_users[0], "delta": elo_deltas["blue"]}],
        }
    else:
        # 2v2 : rôles attacker / defender
        red_roles  = p_roles.get("red",  ["attacker", "defender"])
        blue_roles = p_roles.get("blue", ["attacker", "defender"])
        players_info = []
        for i, (u, role) in enumerate(zip(red_users, red_roles)):
            players_info.append({
                "username": u, "team": "red", "role": role,
                "goals_scored": score["red"],  "shots_total": 0, "shots_on_target": 0,
                "saves": 0, "possession_pct": 0.0,
                "max_ball_speed": stats.get("max_speed", 0), "heatmap": stats.get("heatmap"),
            })
        for i, (u, role) in enumerate(zip(blue_users, blue_roles)):
            players_info.append({
                "username": u, "team": "blue", "role": role,
                "goals_scored": score["blue"], "shots_total": 0, "shots_on_target": 0,
                "saves": 0, "possession_pct": 0.0,
                "max_ball_speed": stats.get("max_speed", 0), "heatmap": stats.get("heatmap"),
            })
        elo_broadcast = {
            "mode": "2v2",
            "red":  [
                {"username": red_users[0],  "delta": elo_deltas.get("red_1", 0)},
                {"username": red_users[1],  "delta": elo_deltas.get("red_2", 0)},
            ],
            "blue": [
                {"username": blue_users[0], "delta": elo_deltas.get("blue_1", 0)},
                {"username": blue_users[1], "delta": elo_deltas.get("blue_2", 0)},
            ],
        }

    await save_match(players_info, score, elo_deltas)

    # Calcule les nouveaux ELOs pour le localStorage des joueurs
    async with pool.acquire() as conn:
        new_elos = {}
        for u in red_users + blue_users:
            new_elos[u] = await conn.fetchval("SELECT elo FROM players WHERE username=$1", u)

    elo_update_msg = {"type": "elo_update", **elo_broadcast, "new_elos": new_elos}

    await broadcast(spectators,  elo_update_msg)
    await broadcast(controllers, elo_update_msg)

    # Envoie aussi aux joueurs connectés au lobby (pour mise à jour localStorage)
    if matchmaking_room:
        for p in matchmaking_room["players"]:
            try:
                await p["ws"].send_str(json.dumps(elo_update_msg))
            except Exception:
                pass

    # Remet la table en idle
    await handle_camera_end()

# ─────────────────────────────────────────────
# Inference worker
# ─────────────────────────────────────────────

async def inference_worker():
    global match_over, replay_in_progress

    while True:
        frame, ts, image_b64 = await frame_queue.get()

        if match_over:
            frame_queue.task_done()
            continue

        # Buffer replay glissant
        frame_replay_buffer.append(image_b64)
        if len(frame_replay_buffer) > REPLAY_BUFFER_SIZE:
            frame_replay_buffer.pop(0)

        loop = asyncio.get_event_loop()
        cx, cy, conf = await loop.run_in_executor(None, detect_ball, frame)

        if cx is not None:
            orig_h, orig_w = frame.shape[:2]
            cx = cx / 640 * orig_w * 2
            cy = cy / 640 * orig_h * 2
            kx_raw, ky_raw = apply_homography(cx, cy)
            if kx_raw is None:
                frame_queue.task_done()
                continue

            kx, ky = kalman_update(kx_raw, ky_raw)
            ball_history.append({"x": kx, "y": ky, "t": ts})

            scorer = check_goal(kx, ky)

            if scorer and not replay_in_progress:
                game.score[scorer] += 1
                replay_before = list(frame_replay_buffer)

                await broadcast(spectators, {
                    "type":  "goal",
                    "team":  scorer,
                    "score": dict(game.score),
                })
                await broadcast(controllers, {
                    "type":  "goal",
                    "team":  scorer,
                    "score": dict(game.score),
                })

                asyncio.create_task(send_replay_after(replay_before, 10))

                if game.score[scorer] >= GOALS_TO_WIN:
                    match_over = True
                    stats      = compute_stats()
                    await broadcast(spectators, {
                        "type":  "match_end",
                        "score": dict(game.score),
                        "stats": stats,
                    })
                    asyncio.create_task(save_match_end(dict(game.score), stats))

            await broadcast(spectators, {
                "type":  "position",
                "x":     kx / CANVAS_W,
                "y":     ky / CANVAS_H,
                "conf":  conf,
                "ts":    ts,
                "score": dict(game.score),
            })

        frame_queue.task_done()

async def send_replay_after(before_frames, n_after):
    global replay_in_progress
    replay_in_progress = True
    target = len(frame_replay_buffer) + n_after
    while len(frame_replay_buffer) < min(target, REPLAY_BUFFER_SIZE):
        await asyncio.sleep(0.05)

    after_frames = frame_replay_buffer[-n_after:] if len(frame_replay_buffer) >= n_after else list(frame_replay_buffer)
    total_frames = len(before_frames) + len(after_frames)
    await broadcast(spectators, {
        "type":   "replay",
        "frames": before_frames + after_frames,
    })
    await asyncio.sleep(total_frames * 0.08 + 0.5)
    replay_in_progress = False

# ─────────────────────────────────────────────
# WebSocket handlers
# ─────────────────────────────────────────────

async def process_camera_message(ws, msg):
    data     = json.loads(msg)
    msg_type = data.get("type")

    if msg_type == "frame":
        loop      = asyncio.get_event_loop()
        image_b64 = data["image"]
        frame     = await loop.run_in_executor(None, decode_base64_to_cv2, image_b64)
        if frame is not None and not frame_queue.full():
            await frame_queue.put((frame, data.get("ts"), image_b64))

    elif msg_type == "calibration_frame":
        loop  = asyncio.get_event_loop()
        frame = await loop.run_in_executor(None, decode_base64_to_cv2, data["image"])
        if frame is None:
            await broadcast(cameras,     {"type": "calibration_failed"})
            await broadcast(controllers, {"type": "calibration_failed"})
            await broadcast(spectators,  {"type": "calibration_failed"})
            return

        corners = await loop.run_in_executor(None, detect_field_corners, frame)
        if corners is None:
            await broadcast(cameras,     {"type": "calibration_failed"})
            await broadcast(controllers, {"type": "calibration_failed"})
            await broadcast(spectators,  {"type": "calibration_failed"})
            return

        fw = data.get("frame_width",  frame.shape[1])
        fh = data.get("frame_height", frame.shape[0])
        store_pending_calibration(corners, fw, fh)

        await broadcast(cameras, {
            "type":    "calibration_preview",
            "corners": corners,
        })

    elif msg_type == "calibration_preview":
        store_pending_calibration(data["corners"], data.get("frame_width", 0), data.get("frame_height", 0))
        await broadcast(controllers, {
            "type":    "calibration_preview",
            "image":   data["image"],
            "corners": data["corners"],
        })

    elif msg_type == "calibration_failed":
        await broadcast(controllers, {"type": "calibration_failed"})
        await broadcast(spectators,  {"type": "calibration_failed"})

async def handle_camera(request):
    ws = web.WebSocketResponse(max_msg_size=10*1024*1024)
    await ws.prepare(request)
    cameras.add(ws)
    await broadcast(controllers, {"type": "camera_ready"})
    await broadcast(spectators,  {"type": "camera_ready"})
    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                await process_camera_message(ws, msg.data)
            elif msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                break
    finally:
        cameras.discard(ws)
    return ws

async def handle_controller(request):
    global match_over, ball_history, frame_replay_buffer
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    controllers.add(ws)
    if cameras:
        await ws.send_str(json.dumps({"type": "camera_ready"}))
    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                data     = json.loads(msg.data)
                msg_type = data.get("type")

                if msg_type == "trigger_calibration":
                    await broadcast(cameras, {"type": "start_calibration"})

                elif msg_type == "set_players":
                    current_match["mode"]  = data.get("mode", "1v1")
                    current_match["red"]   = data.get("red",  [])
                    current_match["blue"]  = data.get("blue", [])
                    current_match["roles"] = data.get("roles", {"red": [], "blue": []})
                    print(f"[MATCH] Mode={current_match['mode']} Rouge={current_match['red']} Bleu={current_match['blue']}")

                elif msg_type == "confirm_calibration":
                    ok = confirm_calibration()
                    if ok:
                        match_over = False
                        ball_history.clear()
                        frame_replay_buffer.clear()
                        game.score["red"]  = 0
                        game.score["blue"] = 0
                        game.ball_in_goal  = False
                        await broadcast(cameras,     {"type": "calibration_ok"})
                        await broadcast(controllers, {"type": "calibration_ok"})
                        await broadcast(spectators,  {"type": "calibration_ok"})
                    else:
                        await broadcast(controllers, {"type": "calibration_failed"})
            elif msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                break
    finally:
        controllers.discard(ws)
    return ws

async def handle_spectator(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    spectators.add(ws)
    try:
        async for msg in ws:
            if msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                break
    finally:
        spectators.discard(ws)
    return ws

# ─────────────────────────────────────────────
# Matchmaking helpers
# ─────────────────────────────────────────────

def table_status_payload():
    """Construit le payload table_status à broadcaster."""
    room = None
    if matchmaking_room:
        room = {
            "mode": matchmaking_room["mode"],
            "players": [
                {"username": p["username"], "display_name": p["display_name"], "elo": p["elo"], "ready": p["ready"]}
                for p in matchmaking_room["players"]
            ],
            "needed": 2 if matchmaking_room["mode"] == "1v1" else 4,
        }
    return {"type": "table_status", "state": table_state, "room": room}

async def broadcast_table_status():
    await broadcast(spectators, table_status_payload())
    if matchmaking_room:
        for p in matchmaking_room["players"]:
            try:
                await p["ws"].send_str(json.dumps(table_status_payload()))
            except Exception:
                pass


async def handle_lobby(request):
    global table_state, matchmaking_room
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    spectators.add(ws)
    await ws.send_str(json.dumps(table_status_payload()))
    try:
        async for raw in ws:
            if raw.type == WSMsgType.TEXT:
                data     = json.loads(raw.data)
                msg_type = data.get("type")

                if msg_type == "mm_join":
                    username     = data.get("username", "").strip().lower()
                    display_name = data.get("display_name", "")
                    elo          = data.get("elo", 1000)
                    mode         = data.get("mode", "1v1")

                    if matchmaking_room and any(p["username"] == username for p in matchmaking_room["players"]):
                        await ws.send_str(json.dumps({"type": "mm_error", "error": "Tu es déjà dans la salle"}))
                        continue

                    if table_state == "idle":
                        matchmaking_room = {"mode": mode, "players": []}
                        table_state = "matchmaking"
                    elif table_state != "matchmaking":
                        await ws.send_str(json.dumps({"type": "mm_error", "error": "Table occupée"}))
                        continue

                    needed = 2 if matchmaking_room["mode"] == "1v1" else 4
                    if len(matchmaking_room["players"]) >= needed:
                        await ws.send_str(json.dumps({"type": "mm_error", "error": "Salle complète"}))
                        continue

                    matchmaking_room["players"].append({
                        "username": username, "display_name": display_name,
                        "elo": elo, "ready": False, "ws": ws
                    })
                    ws_players[ws] = {"username": username, "display_name": display_name, "elo": elo}
                    await broadcast_table_status()

                elif msg_type == "mm_leave":
                    await _mm_remove_player(ws)

                elif msg_type == "mm_ready":
                    if not matchmaking_room:
                        continue
                    for p in matchmaking_room["players"]:
                        if p["ws"] is ws:
                            p["ready"] = True
                            break

                    needed  = 2 if matchmaking_room["mode"] == "1v1" else 4
                    all_in  = len(matchmaking_room["players"]) == needed
                    all_rdy = all(p["ready"] for p in matchmaking_room["players"])

                    if all_in and all_rdy:
                        await _mm_start_match()
                    else:
                        await broadcast_table_status()

            elif raw.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                break
    finally:
        spectators.discard(ws)
        ws_players.pop(ws, None)
        await _mm_remove_player(ws)
    return ws


async def _mm_remove_player(ws):
    global table_state, matchmaking_room
    if not matchmaking_room:
        return
    before = len(matchmaking_room["players"])
    matchmaking_room["players"] = [p for p in matchmaking_room["players"] if p["ws"] is not ws]
    if len(matchmaking_room["players"]) == 0:
        matchmaking_room = None
        table_state = "idle"
    if len(matchmaking_room["players"]) != before if matchmaking_room else before > 0:
        await broadcast_table_status()


async def _mm_start_match():
    """Tout le monde est prêt — démarre la session caméra/contrôleur."""
    global table_state, current_match, matchmaking_room

    players = matchmaking_room["players"]
    mode    = matchmaking_room["mode"]

    if mode == "1v1":
        red_players  = [players[0]]
        blue_players = [players[1]]
    else:
        red_players  = players[:2]
        blue_players = players[2:]

    current_match["mode"]  = mode
    current_match["red"]   = [p["username"] for p in red_players]
    current_match["blue"]  = [p["username"] for p in blue_players]
    current_match["roles"] = {
        "red":  ["solo"] if mode == "1v1" else ["attacker", "defender"],
        "blue": ["solo"] if mode == "1v1" else ["attacker", "defender"],
    }

    table_state = "calibrating"

    # Indique à chaque joueur son rôle assigné (camera pour le 1er, controller pour les autres)
    for i, p in enumerate(players):
        role = "camera" if i == 0 else "controller"
        try:
                await p["ws"].send_str(json.dumps({"type": "mm_start", "role": role, "match": {
                "mode": mode,
                "red":  [{"username": rp["username"], "display_name": rp["display_name"]} for rp in red_players],
                "blue": [{"username": bp["username"], "display_name": bp["display_name"]} for bp in blue_players],
            }}))
        except Exception:
            pass

    await broadcast_table_status()


async def handle_camera_end():
    """Appelé quand le match se termine pour remettre la table en idle."""
    global table_state, matchmaking_room
    table_state      = "idle"
    matchmaking_room = None
    await broadcast_table_status()


async def ws_router(request):
    path = request.path  # e.g. /ws/camera, /ws/lobby, /ws/spectator
    if "/camera" in path:
        return await handle_camera(request)
    elif "/controller" in path:
        return await handle_controller(request)
    elif "/lobby" in path:
        return await handle_lobby(request)
    else:
        return await handle_spectator(request)

# ─────────────────────────────────────────────
# HTTP + main
# ─────────────────────────────────────────────

STATIC_ROOT = Path(__file__).parent

async def http_file_handler(request):
    path = request.path
    if path == "/":
        path = "/index.html"
    file_path = STATIC_ROOT / path.lstrip("/")
    if not file_path.exists() or not file_path.is_file():
        return web.Response(status=404, text="Not Found")
    mime, _ = mimetypes.guess_type(str(file_path))
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(None, file_path.read_bytes)
    return web.Response(body=data, content_type=mime or "application/octet-stream")

async def api_players(request):
    """GET /api/players — retourne la liste des joueurs triée par ELO."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT username, display_name, elo FROM players ORDER BY elo DESC"
        )
    players = [{"username": r["username"], "display_name": r["display_name"], "elo": r["elo"]} for r in rows]
    return web.Response(
        text=json.dumps(players),
        content_type="application/json"
    )

async def api_players_create(request):
    """POST /api/players — crée un nouveau joueur."""
    try:
        body = await request.json()
    except Exception:
        return web.Response(status=400, text=json.dumps({"error": "JSON invalide"}), content_type="application/json")

    username     = (body.get("username") or "").strip()
    display_name = (body.get("display_name") or "").strip()
    if not username or not display_name:
        return web.Response(status=400, text=json.dumps({"error": "username et display_name requis"}), content_type="application/json")

    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO players (username, display_name) VALUES ($1, $2) RETURNING id, username, display_name, elo",
                username, display_name
            )
        player = {"id": str(row["id"]), "username": row["username"], "display_name": row["display_name"], "elo": row["elo"]}
        return web.Response(status=201, text=json.dumps(player), content_type="application/json")
    except Exception as e:
        msg = str(e)
        if "unique" in msg.lower():
            return web.Response(status=409, text=json.dumps({"error": "username déjà pris"}), content_type="application/json")
        return web.Response(status=500, text=json.dumps({"error": msg}), content_type="application/json")

async def api_auth_register(request):
    """POST /api/auth/register — crée un compte joueur avec mot de passe hashé."""
    try:
        body = await request.json()
    except Exception:
        return web.Response(status=400, text=json.dumps({"error": "JSON invalide"}), content_type="application/json")

    username     = (body.get("username") or "").strip().lower()
    display_name = (body.get("display_name") or "").strip()
    password     = (body.get("password") or "").strip()

    if not username or not display_name or not password:
        return web.Response(status=400, text=json.dumps({"error": "username, display_name et password requis"}), content_type="application/json")
    if len(password) < 6:
        return web.Response(status=400, text=json.dumps({"error": "Mot de passe trop court (6 caractères min)"}), content_type="application/json")

    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "INSERT INTO players (username, display_name, password_hash) VALUES ($1, $2, $3) RETURNING id, username, display_name, elo",
                username, display_name, password_hash
            )
        player = {"id": str(row["id"]), "username": row["username"], "display_name": row["display_name"], "elo": row["elo"]}
        return web.Response(status=201, text=json.dumps(player), content_type="application/json")
    except Exception as e:
        msg = str(e)
        if "unique" in msg.lower():
            return web.Response(status=409, text=json.dumps({"error": "Ce pseudo est déjà pris"}), content_type="application/json")
        return web.Response(status=500, text=json.dumps({"error": msg}), content_type="application/json")


async def api_auth_login(request):
    """POST /api/auth/login — vérifie username + password, retourne les infos joueur."""
    try:
        body = await request.json()
    except Exception:
        return web.Response(status=400, text=json.dumps({"error": "JSON invalide"}), content_type="application/json")

    username = (body.get("username") or "").strip().lower()
    password = (body.get("password") or "").strip()

    if not username or not password:
        return web.Response(status=400, text=json.dumps({"error": "username et password requis"}), content_type="application/json")

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, username, display_name, elo, password_hash FROM players WHERE username = $1",
            username
        )

    if row is None:
        return web.Response(status=401, text=json.dumps({"error": "Pseudo introuvable"}), content_type="application/json")
    if not bcrypt.checkpw(password.encode(), row["password_hash"].encode()):
        return web.Response(status=401, text=json.dumps({"error": "Mot de passe incorrect"}), content_type="application/json")

    player = {"id": str(row["id"]), "username": row["username"], "display_name": row["display_name"], "elo": row["elo"]}
    return web.Response(status=200, text=json.dumps(player), content_type="application/json")


async def api_leaderboard(request):
    """GET /api/leaderboard — classement complet calculé dynamiquement."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                p.id, p.username, p.display_name, p.elo,
                COUNT(DISTINCT m.id) AS matches_played,
                COUNT(DISTINCT m.id) FILTER (
                    WHERE (m.player_red_id  = p.id AND m.score_red  > m.score_blue)
                       OR (m.player_blue_id = p.id AND m.score_blue > m.score_red)
                ) AS wins,
                ROUND(
                    100.0 * COUNT(DISTINCT m.id) FILTER (
                        WHERE (m.player_red_id  = p.id AND m.score_red  > m.score_blue)
                           OR (m.player_blue_id = p.id AND m.score_blue > m.score_red)
                    ) / NULLIF(COUNT(DISTINCT m.id), 0), 1
                ) AS winrate_pct,
                ROUND(AVG(s.possession_pct)::NUMERIC, 1) AS avg_possession,
                ROUND(AVG(CASE WHEN s.shots_total > 0 THEN 100.0 * s.shots_on_target / s.shots_total END)::NUMERIC, 1) AS avg_precision_pct
            FROM players p
            LEFT JOIN matches_1v1 m ON p.id IN (m.player_red_id, m.player_blue_id)
            LEFT JOIN match_player_stats_1v1 s ON s.match_id = m.id AND s.player_id = p.id
            GROUP BY p.id
            ORDER BY p.elo DESC
            """
        )
    result = [
        {
            "username":          r["username"],
            "display_name":      r["display_name"],
            "elo":               r["elo"],
            "matches_played":    r["matches_played"],
            "wins":              r["wins"],
            "winrate_pct":       float(r["winrate_pct"])       if r["winrate_pct"]       is not None else None,
            "avg_possession":    float(r["avg_possession"])    if r["avg_possession"]    is not None else None,
            "avg_precision_pct": float(r["avg_precision_pct"]) if r["avg_precision_pct"] is not None else None,
        }
        for r in rows
    ]
    return web.Response(text=json.dumps(result), content_type="application/json")


async def api_player_stats(request):
    """GET /api/players/{username}/stats — stats perso + historique."""
    username = request.match_info["username"].strip().lower()
    pool = get_pool()
    async with pool.acquire() as conn:
        player = await conn.fetchrow(
            "SELECT id, username, display_name, elo FROM players WHERE username = $1", username
        )
        if player is None:
            return web.Response(status=404, text=json.dumps({"error": "Joueur introuvable"}), content_type="application/json")
        player_id = player["id"]

        agg = await conn.fetchrow(
            """
            SELECT
                COUNT(DISTINCT m.id) AS matches_played,
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
            """, player_id
        )
        matches_1v1 = await conn.fetch(
            """
            SELECT score_red, score_blue, played_at, player_red_id,
                   CASE WHEN player_red_id = $1 THEN elo_delta_red ELSE elo_delta_blue END AS elo_delta
            FROM matches_1v1
            WHERE player_red_id = $1 OR player_blue_id = $1
            ORDER BY played_at DESC LIMIT 10
            """, player_id
        )
        matches_2v2 = await conn.fetch(
            """
            SELECT score_red, score_blue, played_at, player_red_1, player_red_2,
                   CASE WHEN player_red_1 = $1 THEN elo_delta_red_1
                        WHEN player_red_2 = $1 THEN elo_delta_red_2
                        WHEN player_blue_1 = $1 THEN elo_delta_blue_1
                        ELSE elo_delta_blue_2 END AS elo_delta
            FROM matches_2v2
            WHERE $1 IN (player_red_1, player_red_2, player_blue_1, player_blue_2)
            ORDER BY played_at DESC LIMIT 10
            """, player_id
        )

    recent = []
    for m in matches_1v1:
        is_red = m["player_red_id"] == player_id
        my, opp = (m["score_red"], m["score_blue"]) if is_red else (m["score_blue"], m["score_red"])
        recent.append({"mode": "1v1", "score_my_team": my, "score_opp": opp,
                       "won": my > opp, "draw": my == opp, "elo_delta": m["elo_delta"],
                       "date": m["played_at"].isoformat()})
    for m in matches_2v2:
        is_red = player_id in (m["player_red_1"], m["player_red_2"])
        my, opp = (m["score_red"], m["score_blue"]) if is_red else (m["score_blue"], m["score_red"])
        recent.append({"mode": "2v2", "score_my_team": my, "score_opp": opp,
                       "won": my > opp, "draw": my == opp, "elo_delta": m["elo_delta"],
                       "date": m["played_at"].isoformat()})
    recent.sort(key=lambda x: x["date"], reverse=True)

    result = {
        "username": player["username"], "display_name": player["display_name"], "elo": player["elo"],
        "matches_played":    agg["matches_played"]    or 0,
        "wins":              agg["wins"]              or 0,
        "draws":             0,
        "winrate_pct":       float(agg["winrate_pct"])       if agg["winrate_pct"]       is not None else None,
        "avg_possession":    float(agg["avg_possession"])    if agg["avg_possession"]    is not None else None,
        "avg_precision_pct": float(agg["avg_precision_pct"]) if agg["avg_precision_pct"] is not None else None,
        "total_goals":       int(agg["total_goals"])         if agg["total_goals"]       is not None else 0,
        "avg_max_speed":     float(agg["avg_max_speed"])     if agg["avg_max_speed"]     is not None else None,
        "recent_matches":    recent[:10],
    }
    return web.Response(text=json.dumps(result), content_type="application/json")


async def main():
    global frame_queue
    frame_queue = asyncio.Queue(maxsize=5)

    await init_db()
    asyncio.create_task(inference_worker())

    app = web.Application(client_max_size=20*1024*1024)
    # WebSocket routes (must be before the catch-all)
    app.router.add_route("GET", "/ws",          ws_router)
    app.router.add_route("GET", "/ws/{tail:.*}", ws_router)
    # API routes
    app.router.add_route("GET",  "/config.json",                      lambda r: web.Response(text=json.dumps({"ws_port": PORT}), content_type="application/json"))
    app.router.add_route("POST", "/api/auth/register",                api_auth_register)
    app.router.add_route("POST", "/api/auth/login",                   api_auth_login)
    app.router.add_route("GET",  "/api/players",                      api_players)
    app.router.add_route("POST", "/api/players",                      api_players_create)
    app.router.add_route("GET",  "/api/leaderboard",                  api_leaderboard)
    app.router.add_route("GET",  "/api/players/{username}/stats",     api_player_stats)
    # Static files catch-all
    app.router.add_route("GET",  "/{path_info:.*}",                   http_file_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()

    print(f"Server on http://0.0.0.0:{PORT}  (HTTP + WS on same port)")

    try:
        await asyncio.Future()
    finally:
        await close_db()

asyncio.run(main())