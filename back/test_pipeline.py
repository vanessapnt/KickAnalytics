import sys
import os
import json
import base64
import time
import cv2
import numpy as np
import onnxruntime as ort

from config import (
    CANVAS_W, CANVAS_H, FIELD_H_PX, GOAL_DEPTH_PX, FIELD_Y0, FIELD_Y1,
    FIELD_W, GOAL_W,
)
from game import (
    game,
    compute_homography,
    apply_homography,
    build_goal_zones,
    confirm_calibration,
    store_pending_calibration,
    check_goal,
)
from zones import compute_attributed_stats, detect_contacts, last_scorer_contact
from vision import detect_ball as detect_ball_local, detect_field_corners

def frame_to_b64(frame, quality=75):
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return base64.b64encode(buf.tobytes()).decode() if ok else ""

def main():
    video_path  = sys.argv[1] if len(sys.argv) > 1 else "test2.mp4"
    server_fps  = float(sys.argv[2]) if len(sys.argv) > 2 else 14.0
    max_frames  = int(sys.argv[3])   if len(sys.argv) > 3 else 500

    if not os.path.exists(video_path):
        print(f"[ERROR] Video '{video_path}' not found")
        sys.exit(1)

    print(f"[+] Opening {video_path}")
    cap = cv2.VideoCapture(video_path)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    print(f"{total} total frames @ {fps:.1f} fps")

    step = max(1, round(fps / server_fps))
    indices = list(range(0, total, step))[:max_frames]
    print(f"[+] server_fps={server_fps:.0f}  video_fps={fps:.1f}  step=1/{step}  max={max_frames}  → {len(indices)} frames")

    corners = None
    goal_top = goal_bottom = None
    for idx in indices[:10]:
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, first_frame = cap.read()
        if not ok:
            continue
        oh, ow = first_frame.shape[:2]
        print("[+] Detecting field corners...")
        corners = detect_field_corners(first_frame)
        if corners:
            store_pending_calibration(corners, ow, oh)
            confirm_calibration()
            goal_top  = game.goal_top
            goal_bottom = game.goal_bottom
            print(f"Corners: tl={corners[0]} tr={corners[1]} br={corners[2]} bl={corners[3]}")
            print(f"Frame: {ow}x{oh}")
            print(f"Top goal: x={goal_top['x1']}->{goal_top['x2']} y={goal_top['y1']}->{goal_top['y2']}")
            print(f"Bottom goal: x={goal_bottom['x1']}->{goal_bottom['x2']} y={goal_bottom['y1']}->{goal_bottom['y2']}")
            break
    else:
        print("[WARN] Corners not detected - homography disabled")

    print(f"[+] Pipeline over {len(indices)} frames...")
    game.ball_in_goal = False
    game.score = {"red": 0, "blue": 0}
    results = []
    inference_times = []

    for i, idx in enumerate(indices):
      cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
      ok, frame = cap.read()
      if not ok:
        continue
      oh, ow = frame.shape[:2]

      t0 = time.time()
      cx_raw, cy_raw, conf = detect_ball_local(frame)
      inference_ms = (time.time() - t0) * 1000
      inference_times.append(inference_ms)

      cx_frame = cy_frame = None
      if cx_raw is not None:
        cx_frame = cx_raw / 640 * ow
        cy_frame = cy_raw / 640 * oh

      cx_canvas = cy_canvas = None
      if cx_frame is not None and game.H_matrix is not None:
        cx_canvas, cy_canvas = apply_homography(cx_frame, cy_frame)

      scored = None
      if cx_canvas is not None and game.goal_top is not None:
        scored = check_goal(cx_canvas, cy_canvas)
        if scored:
          game.score[scored] += 1
          print(f"GOAL {scored.upper()}! frame {idx} score={game.score}")

      frame_draw = frame.copy()
      if corners:
        cv2.polylines(frame_draw, [np.int32(corners)], True, (0, 0, 220), 3)
      if cx_frame is not None:
        cv2.circle(frame_draw, (int(cx_frame), int(cy_frame)), 14, (0, 255, 255), 3)
        cv2.circle(frame_draw, (int(cx_frame), int(cy_frame)), 3, (0, 255, 255), -1)

      results.append({
        "frame_idx": idx,
        "frame_num": i,
        "ts": int(idx / fps * 1000),
        "conf": round(conf, 3),
        "detected": cx_raw is not None,
        "cx_frame": round(cx_frame, 1) if cx_frame is not None else None,
        "cy_frame": round(cy_frame, 1) if cy_frame is not None else None,
        "cx_canvas": round(cx_canvas, 1) if cx_canvas is not None else None,
        "cy_canvas": round(cy_canvas, 1) if cy_canvas is not None else None,
        "kx": round(cx_canvas, 1) if cx_canvas is not None else None,
        "ky": round(cy_canvas, 1) if cy_canvas is not None else None,
        "scored": scored,
        "score_red": game.score["red"],
        "score_blue": game.score["blue"],
        "frame_b64": frame_to_b64(frame_draw, quality=70),
      })

      if (i + 1) % 10 == 0:
        print(f"{i+1}/{len(indices)} processed frames (last inference: {inference_ms:.1f}ms)")

    print(f"\n[Inference times]")
    print(f"min: {min(inference_times):.1f}ms")
    print(f"max: {max(inference_times):.1f}ms")
    print(f"mean: {sum(inference_times)/len(inference_times):.1f}ms")
    print(f"-> theoretical fps: {1000/(sum(inference_times)/len(inference_times)):.1f}fps")

    ball_history = [
        {"x": r["kx"], "y": r["ky"], "t": r["ts"]}
        for r in results if r["kx"] is not None
    ]
    goal_events = [
        {"team": r["scored"], "ts": r["ts"]}
        for r in results if r["scored"]
    ]
    attributed, (blue_poss, red_poss) = compute_attributed_stats(
        ball_history, goal_events, "1v1"
    )
    contacts = detect_contacts(ball_history)

    goal_rods = []
    for r in results:
        if r["scored"]:
            c_scorer = last_scorer_contact(contacts, r["ts"], r["scored"])
            rod = c_scorer["name"] if c_scorer else None
            goal_rods.append({"team": r["scored"], "ts": r["ts"],
                               "frame_idx": r["frame_idx"], "rod": rod})

    print(f"\n[Zone stats — 1v1]")
    for (team, role), s in sorted(attributed.items()):
        print(f"  {team:4s}: goals={s['goals']}  shots={s['shots_total']}  "
              f"on_target={s['shots_on_target']}  saves={s['saves']}")
    print(f"  Possession: blue={blue_poss}%  red={red_poss}%")
    print(f"  Contacts detected: {len(contacts)}")
    for g in goal_rods:
        print(f"  Goal {g['team']:4s} frame={g['frame_idx']}  rod={g['rod']}")

    print("[+] Generating JSON...")
    generate_json(results, corners, goal_top, goal_bottom, contacts, attributed, blue_poss, red_poss, goal_rods)
    print("[+] Done -> frontend/public/pipeline_data/")


def generate_json(results, corners, goal_top, goal_bottom,
                  contacts, attributed, blue_poss, red_poss, goal_rods=None):
    base = os.path.join(os.path.dirname(__file__), "..", "frontend", "public", "pipeline_data")
    os.makedirs(base, exist_ok=True)

    with open(os.path.join(base, "frames.json"), "w", encoding="utf-8") as f:
        json.dump(results, f)

    meta = {
        "goalTop":    goal_top,
        "goalBot":    goal_bottom,
        "contacts":   [{
            "x": c["x"], "y": c["y"], "t": c["t"],
            "team": c["team"], "name": c["name"],
            "role": c["role_2v2"], "deviation": c["deviation"],
        } for c in contacts],
        "matchStats": {
            k[0]: {
                "goals":           v["goals"],
                "shots_total":     v["shots_total"],
                "shots_on_target": v["shots_on_target"],
                "saves":           v["saves"],
            }
            for k, v in attributed.items()
        },
        "possession": {"blue": blue_poss, "red": red_poss},
        "goalRods":   goal_rods or [],
        "canvas": {
            "CW":           CANVAS_W,
            "CH":           CANVAS_H,
            "FY0":          FIELD_Y0,
            "FY1":          FIELD_Y1,
            "FIELD_H_PX":   FIELD_H_PX,
            "GOAL_DEPTH_PX": GOAL_DEPTH_PX,
        },
    }
    with open(os.path.join(base, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f)


if __name__ == "__main__":
    main()