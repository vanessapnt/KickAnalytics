import asyncio, json, mimetypes
from pathlib import Path
from aiohttp import web

from config import PORT
from db import init_db, close_db
import state
from handlers import handle_camera, handle_controller, handle_spectator, inference_worker
from matchmaking import handle_lobby
from api import (
    api_players, api_players_create,
    api_auth_register, api_auth_login,
    api_leaderboard, api_player_stats,
)

STATIC_ROOT = Path(__file__).parent

async def http_file_handler(request):
    path = request.path if request.path != "/" else "/index.html"
    file_path = STATIC_ROOT / path.lstrip("/")
    if not file_path.exists() or not file_path.is_file():
        return web.Response(status=404, text="Not Found")
    mime, _ = mimetypes.guess_type(str(file_path))
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(None, file_path.read_bytes)
    return web.Response(body=data, content_type=mime or "application/octet-stream")

async def ws_router(request):
    path = request.path
    if "/camera" in path: return await handle_camera(request)
    if "/controller" in path: return await handle_controller(request)
    if "/lobby" in path: return await handle_lobby(request)
    return await handle_spectator(request)

async def main():
    import concurrent.futures
    general_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix='cv2')
    asyncio.get_event_loop().set_default_executor(general_executor)

    state.frame_queue = asyncio.Queue(maxsize=2)
    await init_db()
    asyncio.create_task(inference_worker())

    app = web.Application(client_max_size=20*1024*1024)

    app.router.add_route("GET", "/ws", ws_router)
    app.router.add_route("GET", "/ws/{tail:.*}", ws_router)

    app.router.add_route("GET", "/config.json", lambda r: web.Response(text=json.dumps({"ws_port": PORT}), content_type="application/json"))
    app.router.add_route("POST", "/api/auth/register", api_auth_register)
    app.router.add_route("POST", "/api/auth/login", api_auth_login)
    app.router.add_route("GET", "/api/players", api_players)
    app.router.add_route("POST", "/api/players", api_players_create)
    app.router.add_route("GET", "/api/leaderboard", api_leaderboard)
    app.router.add_route("GET", "/api/players/{username}/stats", api_player_stats)

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