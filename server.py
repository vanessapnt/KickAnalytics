import asyncio, json, os, mimetypes
import websockets
from aiohttp import web
from pathlib import Path
from collections import defaultdict
import base64
import numpy as np
import cv2
import onnxruntime as ort
import math

from config import *
from game import (
    game,
    apply_homography,
    kalman_update,
    check_goal,
    store_pending_calibration,
    confirm_calibration,
)

GOALS_TO_WIN = 5
REPLAY_BUFFER_SIZE = 30  # frames gardées en mémoire côté serveur

match_over = False
ball_history = []
frame_replay_buffer = []  # buffer base64 glissant côté serveur

print("Loading ONNX model...")
sess = ort.InferenceSession("model.onnx")
input_name = sess.get_inputs()[0].name
print("Model loaded ✓")

frame_queue: asyncio.Queue = None

cameras     = set()
controllers = set()
spectators  = set()

async def broadcast(targets, msg):
    data = json.dumps(msg)
    await asyncio.gather(
        *[ws.send(data) for ws in targets.copy() if not ws.closed],
        return_exceptions=True
    )

def decode_base64_to_cv2(image_b64):
    img_bytes = base64.b64decode(image_b64.split(',')[1])
    img_array = np.frombuffer(img_bytes, dtype=np.uint8)
    return cv2.imdecode(img_array, cv2.IMREAD_COLOR)

def detect_ball(frame):
    img = cv2.resize(frame, (640, 640))
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    img = img.astype(np.float32) / 255.0
    img = np.transpose(img, (2, 0, 1))
    img = np.expand_dims(img, 0)

    preds = sess.run(None, {input_name: img})[0][0]

    best_idx = np.argmax(preds[4])
    conf = float(preds[4][best_idx])

    if conf < 0.35:
        return None, None, conf

    return float(preds[0][best_idx]), float(preds[1][best_idx]), conf

def detect_field_corners(frame):
    hsv  = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (35, 20, 40), (85, 255, 255))
    kernel = np.ones((15, 15), np.uint8)
    mask   = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    pts = cv2.findNonZero(mask)
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

def compute_stats():
    if len(ball_history) < 2:
        return {}

    speeds  = []
    heatmap = np.zeros((20, 40))
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

async def inference_worker():
    global match_over

    while True:
        frame, ts, image_b64 = await frame_queue.get()

        if match_over:
            frame_queue.task_done()
            continue

        # Mise à jour du buffer replay glissant
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

            if scorer:
                game.score[scorer] += 1

                # Snapshot du buffer au moment du but + 10 frames after
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

                # Capture 10 frames after en attendant les prochaines du worker
                asyncio.create_task(send_replay_after(replay_before, 10))

                if game.score[scorer] >= GOALS_TO_WIN:
                    match_over = True
                    stats = compute_stats()
                    await broadcast(spectators, {
                        "type":  "match_end",
                        "score": dict(game.score),
                        "stats": stats,
                    })

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
    """Attend que n_after nouvelles frames arrivent dans le buffer puis envoie le replay."""
    target = len(frame_replay_buffer) + n_after
    while len(frame_replay_buffer) < min(target, REPLAY_BUFFER_SIZE):
        await asyncio.sleep(0.05)

    after_frames = frame_replay_buffer[-n_after:] if len(frame_replay_buffer) >= n_after else list(frame_replay_buffer)
    await broadcast(spectators, {
        "type":   "replay",
        "frames": before_frames + after_frames,
    })

async def process_camera_message(ws, msg):
    data = json.loads(msg)
    msg_type = data.get("type")

    if msg_type == "frame":
        loop = asyncio.get_event_loop()
        image_b64 = data["image"]
        frame = await loop.run_in_executor(None, decode_base64_to_cv2, image_b64)
        if frame is not None and not frame_queue.full():
            await frame_queue.put((frame, data.get("ts"), image_b64))

    elif msg_type == "calibration_frame":
        loop = asyncio.get_event_loop()
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
        fw = data.get("frame_width",  0)
        fh = data.get("frame_height", 0)
        store_pending_calibration(data["corners"], fw, fh)

        await broadcast(controllers, {
            "type":    "calibration_preview",
            "image":   data["image"],
            "corners": data["corners"],
        })

    elif msg_type == "calibration_failed":
        await broadcast(controllers, {"type": "calibration_failed"})
        await broadcast(spectators,  {"type": "calibration_failed"})

async def handle_camera(ws):
    cameras.add(ws)
    await broadcast(controllers, {"type": "camera_ready"})
    await broadcast(spectators,  {"type": "camera_ready"})
    try:
        async for msg in ws:
            await process_camera_message(ws, msg)
    finally:
        cameras.discard(ws)

async def handle_controller(ws):
    controllers.add(ws)
    if cameras:
        await ws.send(json.dumps({"type": "camera_ready"}))
    try:
        async for msg in ws:
            data = json.loads(msg)
            msg_type = data.get("type")

            if msg_type == "trigger_calibration":
                await broadcast(cameras, {"type": "start_calibration"})

            elif msg_type == "confirm_calibration":
                ok = confirm_calibration()
                if ok:
                    await broadcast(cameras,     {"type": "calibration_ok"})
                    await broadcast(controllers, {"type": "calibration_ok"})
                    await broadcast(spectators,  {"type": "calibration_ok"})
                else:
                    await broadcast(controllers, {"type": "calibration_failed"})

    finally:
        controllers.discard(ws)

async def handle_spectator(ws):
    spectators.add(ws)
    try:
        async for msg in ws:
            pass
    finally:
        spectators.discard(ws)

async def ws_handler(ws):
    path = ws.path
    if path.startswith("/camera"):
        await handle_camera(ws)
    elif path.startswith("/controller"):
        await handle_controller(ws)
    else:
        await handle_spectator(ws)

STATIC_ROOT = Path(__file__).parent
HTTP_PORT   = PORT

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

async def main():
    global frame_queue
    frame_queue = asyncio.Queue(maxsize=5)
    asyncio.create_task(inference_worker())

    ws_server = await websockets.serve(ws_handler, "0.0.0.0", WS_PORT)

    app = web.Application()
    app.router.add_route("GET", "/config.json", lambda r: web.Response(
        text=__import__('json').dumps({"ws_port": WS_PORT}),
        content_type="application/json"
    ))
    app.router.add_route("GET", "/{path_info:.*}", http_file_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", HTTP_PORT)
    await site.start()

    print(f"HTTP  on http://0.0.0.0:{HTTP_PORT}")
    print(f"WS    on ws://0.0.0.0:{WS_PORT}")
    await asyncio.Future()

asyncio.run(main())