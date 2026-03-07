import asyncio, json
import websockets
from pathlib import Path
from collections import defaultdict
import http

from config import *

cameras        = set()
spectators     = set() #len(spectators) = 0
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
    if data.get("type") == "calibration": # 4 corners found in the camera frame, with their coordinates and the frame dimensions (frame_width, frame_height)
        pass
    elif data.get("type") == "calibration_failed": # field detection failed
        await broadcast(spectators, {"type": "calibration_failed"})
    elif data.get("type") == "position": # ball position detected in the camera frame, with its coordinates (x,y) and confidence level (conf)
        pass

async def handle_camera(ws):
    ip = ws.remote_address[0]
    cameras.add(ws)
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

# spectator ("start calibration")-> server -> camera
async def process_spectator_message(msg):
    try:
        data = json.loads(msg)
    except json.JSONDecodeError:
        return
    if data.get("type") == "trigger_calibration":
        await broadcast(cameras, {"type": "start_calibration"}) # cameras : set of ws

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
        async for msg in ws: # stops when StopAsyncIteration is raised by await self.recv() in __anext__(self) in ws when the connection is closed.
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
    await ws.send(json.dumps({"type": "score", "score": {"red": 0, "blue": 0}}))

# normal def -> regular function.
# async def -> coroutine function (it returns a coroutine object when called).
# To run it, we need await (inside another coroutine) or asyncio.run(...) at the top level.
# Optionally, we can run it as a parallel task with asyncio.create_task(...)

# receives all websocket connections and dispatches them to the appropriate handler based on the URL path (/camera for cameras, / for spectators). 
async def ws_handler(ws):
    if not connection_allowed(ws):
        await ws.close()
        return
    ip = ws.remote_address[0]
    ip_connections[ip] += 1
    try:
        if "/camera" in ws.request.path:
            await handle_camera(ws)
        else:
            await handle_spectator(ws)
    finally:
        ip_connections[ip] = max(0, ip_connections[ip] - 1) # nb of connections never negative

STATIC_FILES = {
    "/":               "index.html",
    "/index.html":     "index.html",
    "/camera.html":    "camera.html",
    "/spectator.html": "spectator.html",
}

async def http_handler(path, headers):
    path = path.split("?")[0] # /camera.html?foo=1 -> /camera.html
    upgrade_hdr = headers.get("Upgrade", "")
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
    return http.HTTPStatus.OK, [("Content-Type", "text/html; charset=utf-8")], content

# With websockets.serve(...), the library creates an underlying TCP listening socket (bind/listen/accept).
# For each accepted client, it creates a connection and gives you the ws object (a WebSocket wrapper) in the handler.
async def main():
    #build_goal_zones()
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