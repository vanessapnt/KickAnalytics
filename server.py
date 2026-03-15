import asyncio, json
import websockets
from pathlib import Path
from collections import defaultdict
import http

from config import *
from game import (
    game,
    store_pending_calibration,
    confirm_calibration,
    apply_homography,
    kalman_update,
    check_goal,
)

cameras        = set()
spectators     = set()
ip_connections = defaultdict(int) # initialize to 0 for any new key

async def broadcast(targets, msg):
    data = json.dumps(msg)
    for ws in targets.copy(): # err : Set changed size during iteration
        try:
            await ws.send(data)
        except Exception:
            targets.discard(ws)

class RateLimiter:
    def __init__(self, max_per_sec):
        self.max      = max_per_sec
        self.count    = 0
        self.reset_at = asyncio.get_running_loop().time() + 1

    def allow(self):
        now = asyncio.get_running_loop().time()
        if now > self.reset_at:
            self.count    = 0
            self.reset_at = now + 1
        self.count += 1
        return self.count <= self.max

# Limits the number of simultaneous connections per IP to prevent abuse or overload
def connection_allowed(ws):
    ip = ws.remote_address[0] # ws.remote_address -> tuple (ip, port)
    if ip_connections[ip] >= MAX_CONNECTIONS_PER_IP:
        print(f"IP blocked: {ip}")
        return False
    return True

async def process_camera_message(msg):
    try:
        data = json.loads(msg)
    except json.JSONDecodeError:
        return

    # "Calibrer" btn (camera) -> preview to spectator screen
    if data.get("type") == "calibration_preview":
        store_pending_calibration(
            data.get("corners"),
            data.get("frame_width"),
            data.get("frame_height"),
        )
        await broadcast(spectators, {
            "type":         "calibration_preview",
            "image":        data.get("image"),
            "corners":      data.get("corners"),
            "frame_width":  data.get("frame_width"),
            "frame_height": data.get("frame_height"),
        })

    # "OK" btn -> confirm calibration, build homography and goal zones, reset kalman filter
    elif data.get("type") == "confirm_calibration":
        confirm_calibration()
        await broadcast(spectators, {"type": "calibration_ok"})
        await broadcast(cameras,    {"type": "calibration_ok"})

    elif data.get("type") == "calibration_failed":
        await broadcast(spectators, {"type": "calibration_failed"})

    elif data.get("type") == "position":
        # camera coordinates -> canvas coordinates
        cx, cy = apply_homography(data["x"], data["y"])
        if cx is None:
            return
        kx, ky = kalman_update(cx, cy)
        # normalize to [0, 1] for the spectator canvas
        nx = kx / CANVAS_W
        ny = ky / CANVAS_H
        scorer = check_goal(kx, ky)
        if scorer:
            game.score[scorer] += 1
            await broadcast(spectators, {"type": "goal", "team": scorer, "score": dict(game.score)})
        await broadcast(spectators, {
            "type":  "position",
            "x":     nx,
            "y":     ny,
            "conf":  data.get("conf"),
            "ts":    data.get("ts"),
            "score": dict(game.score),
        })

async def handle_camera(ws):
    ip = ws.remote_address[0]
    cameras.add(ws) # camera opened a new websocket connection
    print(f"Camera connected ({ip})")
    await broadcast(spectators, {"type": "camera_ready"})
    limiter = RateLimiter(MAX_MESSAGES_PER_SEC_CAM)
    try:
        async for msg in ws:
            if limiter.allow():
                await process_camera_message(msg)
    finally:
        cameras.discard(ws)
        print(f"Camera disconnected ({ip})")

async def process_spectator_message(msg):
    try:
        data = json.loads(msg)
    except json.JSONDecodeError:
        return
    if data.get("type") == "trigger_calibration":
        await broadcast(cameras, {"type": "start_calibration"})
    elif data.get("type") == "confirm_calibration":
        confirm_calibration()
        await broadcast(spectators, {"type": "calibration_ok"})
        await broadcast(cameras,    {"type": "calibration_ok"})

async def handle_spectator(ws):
    ip = ws.remote_address[0]
    if len(spectators) >= MAX_SPECTATORS:
        print(f"Too many spectators: {ip}")
        await ws.close()
        return
    spectators.add(ws)
    print(f"Spectator connected ({ip}) — total: {len(spectators)}")
    await sync_client_state(ws)
    limiter = RateLimiter(MAX_MESSAGES_PER_SEC_SPECT)
    try:
        async for msg in ws: # stops when StopAsyncIteration is raised by await self.recv() in __anext__(self) in ws when the connection is closed
            if limiter.allow():
                await process_spectator_message(msg)
    finally:
        spectators.discard(ws) # websocket closed or error, remove from spectators set
        print(f"Spectator disconnected ({ip})")

# json.dumps(obj) : Python -> JSON string
# json.loads(str) : JSON string-> Python
async def sync_client_state(ws):
    if cameras:
        await ws.send(json.dumps({"type": "camera_ready"}))
    await ws.send(json.dumps({"type": "score", "score": dict(game.score)}))

# normal def -> regular function.
# async def -> coroutine function (it returns a coroutine object when called).
# To run it, we need await (inside another coroutine) or asyncio.run(...) at the top level.
# Optionally, we can run it as a parallel task with asyncio.create_task(...)

# receives all websocket connections and dispatches them to the appropriate handler based on the URL path
async def ws_handler(ws):
    if not connection_allowed(ws):
        await ws.close()
        return
    ip = ws.remote_address[0]
    ip_connections[ip] += 1
    try:
        if "/camera" in ws.path:
            await handle_camera(ws)
        else:
            await handle_spectator(ws)
    finally:
        ip_connections[ip] = max(0, ip_connections[ip] - 1) # nb of connections never negative

STATIC_FILES = {
    "/" : "index.html",
    "/index.html" : "index.html",
    "/camera.html" : "camera.html",
    "/controller.html" : "controller.html",
    "/model.onnx": "model.onnx",
    "/test.mp4" : "test.mp4",
}

async def http_handler(path, headers):
    path = path.split("?")[0] # /camera.html?foo=1 -> /camera.html
    upgrade_hdr    = headers.get("Upgrade", "")
    connection_hdr = headers.get("Connection", "")

    is_ws_upgrade = (
        upgrade_hdr.lower() == "websocket"
        and "upgrade" in connection_hdr.lower()
    )
    if is_ws_upgrade:
        return None # it's a websocket upgrade request, lets ws_handler take care of it

    filename = STATIC_FILES.get(path)
    # The response sent to the client must be a tuple of 3 elements: (status, headers, body)
    if not filename:
        return http.HTTPStatus.NOT_FOUND, [], b"Not Found\n" # b : string -> bytes
    filepath = Path(__file__).parent / filename # absolute path to the static file
    if not filepath.exists():
        return http.HTTPStatus.NOT_FOUND, [], b"Not Found\n"
    content = filepath.read_bytes()
    content_type = "application/octet-stream" if path.endswith(".onnx") else "text/html; charset=utf-8"
    return http.HTTPStatus.OK, [("Content-Type", content_type)], content

# With websockets.serve(...), the library creates an underlying TCP listening socket (bind/listen/accept).
# For each accepted client, it creates a connection and gives you the ws object (a WebSocket wrapper) in the handler.
async def main():
    print(f"Server running on port {PORT}")
    async with websockets.serve(
        ws_handler,
        "0.0.0.0", # listen on all interfaces, not just localhost
        PORT,
        process_request=http_handler,
    ):
        await asyncio.Future()

asyncio.run(main())

# In this project, all `ws.` methods we use for network communication
# (send, recv, close) are coroutines (`async def`) and must be called with `await`.
# Attributes like ws.remote_address or ws.state are regular values and do not require await.