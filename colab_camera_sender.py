import asyncio
import argparse
import base64
import json
import time
from contextlib import suppress
import cv2
import aiohttp
import numpy as np


async def login(session: aiohttp.ClientSession, base_url: str, username: str, password: str) -> bool:
    async with session.post(
        f"{base_url}/api/auth/login",
        json={"username": username, "password": password},
    ) as resp:
        if resp.status != 200:
            body = await resp.text()
            print(f"[ERR] Login failed ({resp.status}): {body}")
            return False
        print(f"[OK] Logged in as '{username}'")
        return True


def frame_to_b64(frame, quality=75) -> str:
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        return ""
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode()


def b64_to_frame(image_b64: str):
    try:
        payload = image_b64.split(",", 1)[1]
        img_bytes = base64.b64decode(payload)
        img_array = np.frombuffer(img_bytes, dtype=np.uint8)
        return cv2.imdecode(img_array, cv2.IMREAD_COLOR)
    except Exception:
        return None


def draw_corners_preview(image_b64: str, corners) -> str:
    frame = b64_to_frame(image_b64)
    if frame is None:
        return image_b64
    if not corners or len(corners) < 4:
        return image_b64

    try:
        pts = np.array(corners, dtype=np.int32).reshape((-1, 1, 2))
        cv2.polylines(frame, [pts], isClosed=True, color=(8, 56, 121), thickness=4)
        return frame_to_b64(frame, quality=80) or image_b64
    except Exception:
        return image_b64


async def send_video(ws_url: str, video_path: str, target_fps: float, loop: bool, session: aiohttp.ClientSession):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"[ERR] Cannot open video: {video_path}")
        return

    video_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    step = max(1, round(video_fps / target_fps))
    loop_label = " (boucle infinie)" if loop else ""
    print(f"[+] Video: {total} frames @ {video_fps:.1f} fps — envoi toutes les {step} frames ({target_fps:.0f} fps){loop_label}")

    async with session.ws_connect(ws_url, max_msg_size=10 * 1024 * 1024) as ws:
        print(f"[OK] WebSocket connecté: {ws_url}")

        send_lock = asyncio.Lock()
        latest = {"image": "", "width": 0, "height": 0}

        async def ws_send(payload: dict):
            async with send_lock:
                await ws.send_str(json.dumps(payload))

        async def ws_listener():
            async for incoming in ws:
                if incoming.type != aiohttp.WSMsgType.TEXT:
                    continue
                try:
                    data = json.loads(incoming.data)
                except Exception:
                    continue

                msg_type = data.get("type")
                if msg_type == "start_calibration":
                    if not latest["image"]:
                        print("[WARN] Calibration demandée mais aucune frame disponible pour le moment")
                        continue
                    await ws_send({
                        "type": "calibration_frame",
                        "image": latest["image"],
                        "frame_width": latest["width"],
                        "frame_height": latest["height"],
                    })
                    print("[OK] Frame de calibration envoyée")

                elif msg_type == "calibration_preview":
                    if not latest["image"]:
                        continue
                    preview_image = draw_corners_preview(latest["image"], data.get("corners", []))
                    await ws_send({
                        "type": "calibration_preview",
                        "image": preview_image,
                        "corners": data.get("corners", []),
                        "frame_width": latest["width"],
                        "frame_height": latest["height"],
                    })
                    print("[OK] Preview calibration renvoyée au contrôleur")

                elif msg_type == "calibration_ok":
                    print("[OK] Calibration confirmée par le contrôleur")

        listener_task = asyncio.create_task(ws_listener())

        sent = 0
        interval = 1.0 / target_fps
        iteration = 0

        try:
            while True:
                iteration += 1
                if loop and iteration > 1:
                    print(f"[~] Reprise de la vidéo (boucle {iteration})")

                frame_idx = 0
                while True:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
                    ok, frame = cap.read()
                    if not ok:
                        break

                    oh, ow = frame.shape[:2]
                    b64 = frame_to_b64(frame)
                    if not b64:
                        frame_idx += step
                        continue

                    latest["image"] = b64
                    latest["width"] = ow
                    latest["height"] = oh

                    msg = {
                        "type": "frame",
                        "image": b64,
                        "ts": int(time.time() * 1000),
                        "frame_width": ow,
                        "frame_height": oh,
                    }
                    await ws_send(msg)
                    sent += 1

                    if sent % 20 == 0:
                        print(f"  {sent} frames envoyées (frame vidéo {frame_idx}/{total})")

                    frame_idx += step
                    await asyncio.sleep(interval)

                if not loop:
                    break
        finally:
            listener_task.cancel()
            with suppress(asyncio.CancelledError):
                await listener_task

    cap.release()
    print(f"[+] Terminé — {sent} frames envoyées")


async def main(args):
    base_url = args.server.rstrip("/")
    ws_url = base_url.replace("https://", "wss://").replace("http://", "ws://") + "/ws/camera"

    async with aiohttp.ClientSession() as session:
        ok = await login(session, base_url, args.user, args.password)
        if not ok:
            return
        await send_video(ws_url, args.video, args.fps, args.loop, session)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--server",   required=True, help="URL du serveur, ex: https://mon-serveur.run.app")
    parser.add_argument("--video",    default="test.mp4", help="Chemin vers la vidéo (défaut: test.mp4)")
    parser.add_argument("--user",     required=True, help="Nom d'utilisateur admin")
    parser.add_argument("--password", required=True, help="Mot de passe")
    parser.add_argument("--fps",      type=float, default=14.0, help="FPS d'envoi (défaut: 14)")
    parser.add_argument("--loop",     action="store_true", help="Rejouer la vidéo en boucle infinie")
    args = parser.parse_args()
    asyncio.run(main(args))
