import asyncio, mimetypes, os
from pathlib import Path
from aiohttp import web

from config import PORT

from db import init_db, close_db
import state
from handlers import handle_camera, handle_controller, handle_spectator, inference_worker
from matchmaking import handle_lobby
from auth_session import get_session_user_from_request
from api import (
    api_auth_register, api_auth_login, api_auth_logout,
    api_leaderboard, api_player_stats, api_debug_dump_sets,
)

# Comma-separated list of allowed origins, e.g.: CORS_ORIGINS=https://kickanalytics.pages.dev,http://localhost:5173
_CORS_ORIGINS = set(
    o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()
)

# middleware is a function that runs for every request before the handler, needed for CORS
# handled by Cloudflare Worker in production, but needed for local development with separate frontend server
# TODO : can be replaced later by Vite proxy
@web.middleware
async def cors_middleware(request, handler):
    origin = request.headers.get("Origin", "") # address of the frontend server that made the request, e.g. http://localhost:5173 or pages.dev
    if request.method == "OPTIONS": # preflight request for CORS, we just respond with the appropriate headers without calling the handler
        resp = web.Response(status=204) # ok -> added on web cache and used for the actual request
    else:
        try:
            resp = await handler(request)
        except web.HTTPException as exc:
            resp = exc
    # e.g curl -> origin is empty -> don't need CORS headers
    # _CORS_ORIGINS empty -> we allow all origins
    if origin and (not _CORS_ORIGINS or origin in _CORS_ORIGINS):
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Access-Control-Allow-Credentials"] = "true" # allows cookies
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp

STATIC_ROOT = Path(__file__).parent.parent
DIST_ROOT = STATIC_ROOT / "frontend" / "dist"
USE_REACT = DIST_ROOT.exists()

PUBLIC_HTML_PATHS = {"/", "/index.html", "/test_pipeline.html"}

def _page_access_cookie_for(path: str):
    if path.endswith("controller.html"):
        return "controller"
    if path.endswith("camera.html"):
        return "camera"
    return None

async def http_file_handler(request):
    request_path = request.path

    REACT_ROUTES = {"/", "/auth", "/controller", "/camera"}

    if USE_REACT: # if dist/ exists, React built
        # Serve Vite build assets (fingerprinted JS/CSS)
        if request_path.startswith("/assets/") or request_path == "/favicon.ico":
            asset_path = DIST_ROOT / request_path.lstrip("/")
            if asset_path.exists() and asset_path.is_file():
                mime, _ = mimetypes.guess_type(str(asset_path))
                data = await asyncio.get_event_loop().run_in_executor(None, asset_path.read_bytes)
                return web.Response(body=data, content_type=mime or "application/octet-stream")
            return web.Response(status=404, text="Not Found")
        # Serve dist/index.html for all React routes (client-side routing)
        if request_path in REACT_ROUTES:
            spa_html = DIST_ROOT / "index.html"
            data = await asyncio.get_event_loop().run_in_executor(None, spa_html.read_bytes)
            return web.Response(body=data, content_type="text/html")

    # Legacy mode (no dist/ build) — serve raw HTML files with cookie checks
    if request_path.endswith(".html") and request_path not in PUBLIC_HTML_PATHS:
        if not get_session_user_from_request(request): # checks ka_session cookie -> not logged in
            raise web.HTTPFound("/") # raise throws an exception that aiohttp catches and turns into redirection response (HTTP 302)
        expected_cookie = _page_access_cookie_for(request_path) # checks ka_page_access cookie : "controller" or "camera" (single-use before serving the page)
        if expected_cookie and request.cookies.get("ka_page_access") != expected_cookie:
            raise web.HTTPFound("/")

    # we find the file and read it (check project root first, then dist/)
    path = request_path if request_path != "/" else "/index.html"
    file_path = STATIC_ROOT / path.lstrip("/")
    if not file_path.exists() or not file_path.is_file():
        file_path = DIST_ROOT / path.lstrip("/")
    if not file_path.exists() or not file_path.is_file():
        return web.Response(status=404, text="Not Found")
    mime, _ = mimetypes.guess_type(str(file_path)) # guess the type based on the file extension (e.g. .html -> text/html)
    loop = asyncio.get_event_loop()
    # None means to use the default executor bc file_path.read_bytes is blocking
    data = await loop.run_in_executor(None, file_path.read_bytes)

    # we can return the content
    response = web.Response(body=data, content_type=mime or "application/octet-stream") #  to download it bc display is impossible (e.g. model.onnx)
    if request_path.endswith(".html") and request_path not in PUBLIC_HTML_PATHS:
        response.del_cookie("ka_page_access")
        # cookie is single-use, so we delete it after checking it
    return response

async def ws_router(request):
    path = request.path
    if "/camera" in path: return await handle_camera(request)
    if "/controller" in path: return await handle_controller(request)
    if "/lobby" in path: return await handle_lobby(request)
    return await handle_spectator(request)

async def main():
    import concurrent.futures
    # ThreadPoolExecutor or ProcessPoolExecutor
    general_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix='cv2')
    # threads called cv2_0 and cv2_1
    # if 10 tasks, only 2 active at a time, the rest wait in a queue
    asyncio.get_event_loop().set_default_executor(general_executor)
    # run_in_executor(None, blocking_function) -> fast operations: reading a file, decoding a base64 image, detecting field corners
    # run_in_executor(_inference_executor, blocking_function) -> slow operations: running the full model inference

    state.frame_queue = asyncio.Queue(maxsize=2) # can wait
    await init_db()
    asyncio.create_task(inference_worker())

    app = web.Application(client_max_size=20*1024*1024) # 20 MB max for websocket messages (for the base64 frames)

    app.router.add_route("GET", "/ws", ws_router)
    app.router.add_route("GET", "/ws/{tail:.*}", ws_router)

    app.router.add_route("POST", "/api/auth/register", api_auth_register)
    app.router.add_route("POST", "/api/auth/login", api_auth_login)
    app.router.add_route("POST", "/api/auth/logout", api_auth_logout)
    app.router.add_route("GET", "/api/leaderboard", api_leaderboard)
    app.router.add_route("GET", "/api/players/{username}/stats", api_player_stats)

    app.router.add_route("POST", "/api/debug/dump-sets", api_debug_dump_sets)
    
    # catch-all for static files so never returns 404 automatically, we handle it in http_file_handler
    app.router.add_route("GET", "/{path_info:.*}", http_file_handler) 

    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    print(f"Server on http://0.0.0.0:{PORT}")

    try:
        await asyncio.Future()
    finally:
        await close_db()

asyncio.run(main())