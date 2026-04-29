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
    video_path  = sys.argv[1] if len(sys.argv) > 1 else "test.mp4"
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

    print("[+] Generating HTML...")
    generate_html(results, corners, goal_top, goal_bottom, contacts, attributed, blue_poss, red_poss, goal_rods)
    print("[+] Done -> frontend/public/test_pipeline.html")


def generate_html(results, corners, goal_top, goal_bottom,
                  contacts, attributed, blue_poss, red_poss, goal_rods=None):
    data_json        = json.dumps(results)
    corners_json     = json.dumps(corners)
    goal_top_json    = json.dumps(goal_top)
    goal_bottom_json = json.dumps(goal_bottom)
    contacts_json    = json.dumps([{
        "x": c["x"], "y": c["y"], "t": c["t"],
        "team": c["team"], "name": c["name"],
        "role": c["role_2v2"], "deviation": c["deviation"],
    } for c in contacts])
    goal_rods_json   = json.dumps(goal_rods or [])
    stats_json = json.dumps({
        k[0]: {
            "goals":           v["goals"],
            "shots_total":     v["shots_total"],
            "shots_on_target": v["shots_on_target"],
            "saves":           v["saves"],
        }
        for k, v in attributed.items()
    })
    poss_json = json.dumps({"blue": blue_poss, "red": red_poss})

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Pipeline Debug KickAnalytics</title>
<style>
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
:root {{
  --red:#e50914; --bg:#111; --card:#1b1b2f; --text:#f0f0f0;
  --muted:#888; --border:#2a2a3f; --green:#4caf50; --yellow:#ffc107;
}}
html, body {{ height: 100%; font-family: sans-serif; background: var(--bg); color: var(--text); overflow: hidden; }}

header {{
  height: 50px;
  background: var(--red); padding: 0 20px;
  display: flex; align-items: center; justify-content: space-between;
  flex-shrink: 0;
}}
.logo {{ font-size: 17px; font-weight: 900; color: white; }}
.score-badge {{ background: rgba(255,255,255,0.2); border-radius: 8px; padding: 5px 16px; font-size: 16px; font-weight: 900; color: white; }}

.layout {{
  display: grid;
  grid-template-columns: 1fr 320px 240px;
  gap: 10px;
  padding: 10px;
  height: calc(100vh - 50px);
}}

.panel {{
  background: var(--card); border-radius: 10px; border: 1px solid var(--border);
  display: flex; flex-direction: column; overflow: hidden; min-height: 0;
}}
.panel-title {{
  font-size: 10px; font-weight: 700; color: var(--muted);
  text-transform: uppercase; letter-spacing: 1.5px;
  padding: 8px 14px 6px; border-bottom: 1px solid var(--border); flex-shrink: 0;
}}
.frame-wrap {{
  flex: 1; display: flex; align-items: center; justify-content: center;
  overflow: hidden; background: #000; position: relative; min-height: 0;
}}
#frameImg {{ max-width: 100%; max-height: 100%; object-fit: contain; display: block; }}
.frame-overlay {{
  position: absolute; top: 8px; left: 8px;
  background: rgba(0,0,0,0.75); border-radius: 6px;
  padding: 3px 10px; font-size: 12px; font-weight: 700; color: white;
}}
.goal-flash {{
  position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
  font-size: 52px; font-weight: 900; background: rgba(229,9,20,0.35);
  animation: flashIn 0.3s ease; pointer-events: none;
}}
@keyframes flashIn {{ from {{ opacity:0;transform:scale(0.7) }} to {{ opacity:1;transform:scale(1) }} }}

.nav-bar {{
  display: flex; align-items: center; gap: 8px;
  padding: 8px 12px; border-top: 1px solid var(--border); flex-shrink: 0;
}}
.btn {{
  background: var(--card); border: 1.5px solid var(--border);
  color: var(--text); border-radius: 8px; padding: 7px 14px;
  font-size: 12px; font-weight: 800; cursor: pointer; font-family: sans-serif;
  transition: all 0.15s; white-space: nowrap;
}}
.btn:hover {{ border-color: var(--red); color: var(--red); }}
.btn.active, .btn-red {{ background: var(--red); border-color: var(--red); color: white; }}
.btn:disabled {{ opacity: 0.3; cursor: not-allowed; }}
.frame-counter {{ flex: 1; text-align: center; font-size: 12px; font-weight: 700; color: var(--muted); }}
input[type=range] {{ flex: 1; accent-color: var(--red); }}
.canvas-wrap {{
  flex: 1; display: flex; align-items: center; justify-content: center;
  overflow: hidden; padding: 8px; min-height: 0;
}}
#terrainCanvas {{
  max-width: 100%; max-height: 100%;
  object-fit: contain;
  border-radius: 4px;
}}
.stats-body {{ flex: 1; overflow-y: auto; padding: 10px 12px; display: flex; flex-direction: column; gap: 6px; min-height: 0; }}
.stat-row {{
  display: flex; justify-content: space-between; align-items: center;
  padding: 6px 10px; background: rgba(255,255,255,0.04); border-radius: 7px; font-size: 11px;
}}
.stat-label {{ color: var(--muted); font-weight: 700; }}
.stat-val {{ font-weight: 900; }}
.stat-val.yellow {{ color: var(--yellow); }}
.pill {{ display: inline-block; border-radius: 5px; padding: 2px 8px; font-size: 10px; font-weight: 800; }}
.pill-green {{ background: rgba(76,175,80,0.25); color: #81c784; }}
.pill-red   {{ background: rgba(229,9,20,0.25);  color: #ef9a9a; }}
.pill-grey  {{ background: rgba(255,255,255,0.08); color: var(--muted); }}
.conf-bar {{ height: 4px; background: var(--border); border-radius: 2px; overflow: hidden; margin-top: 3px; }}
.conf-fill {{ height: 100%; border-radius: 2px; transition: width 0.2s; }}
.goal-log {{ display: flex; flex-direction: column; gap: 4px; max-height: 130px; overflow-y: auto; }}
.goal-entry {{ font-size: 11px; font-weight: 700; padding: 4px 10px; border-radius: 6px; }}
.goal-entry.blue {{ background: rgba(21,101,192,0.25); color: #90caf9; }}
.goal-entry.red  {{ background: rgba(229,9,20,0.25);   color: #ef9a9a; }}
.sep {{ font-size: 9px; font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: 1px; padding: 4px 0 2px; }}
</style>
</head>
<body>

<header>
  <div class="logo">🔬 Pipeline Debug KickAnalytics</div>
  <div class="score-badge">🔴 <span id="scoreRed">0</span> – <span id="scoreBlue">0</span> 🔵</div>
</header>

<div class="layout">
  <div class="panel">
    <div class="panel-title" id="panelVideoTitle">Frame vidéo</div>
    <div class="frame-wrap">
      <img id="frameImg" src="" alt="frame"/>
      <div class="frame-overlay" id="frameLabel">—</div>
      <div class="goal-flash" id="goalFlash" style="display:none"></div>
    </div>
    <div class="nav-bar">
      <button class="btn" id="btnPrev" onclick="navigate(-1)">◀</button>
      <input type="range" id="scrubber" min="0" value="0" oninput="goTo(+this.value)"/>
      <button class="btn" id="btnNext" onclick="navigate(+1)">▶</button>
    </div>
    <div class="nav-bar" style="border-top:none;padding-top:0">
      <button class="btn" id="btnPlay" onclick="togglePlay()" style="flex:1">▶ Play</button>
      <div class="frame-counter" id="frameCounter">0 / 0</div>
      <button class="btn btn-red" onclick="goTo(0)">⏮</button>
    </div>
  </div>
  <div class="panel">
    <div class="panel-title">Terrain canvas {CANVAS_W}x{CANVAS_H}px (terrain {CANVAS_W}x{FIELD_H_PX} + buts {GOAL_DEPTH_PX}px)</div>
    <div class="canvas-wrap" id="canvasWrap">
      <canvas id="terrainCanvas" width="{CANVAS_W}" height="{CANVAS_H}"></canvas>
    </div>
  </div>
  <div class="panel">
    <div class="panel-title">Pipeline</div>
    <div class="stats-body">
      <div class="stat-row">
        <span class="stat-label">Frame vidéo</span>
        <span class="stat-val" id="sFrameIdx">—</span>
      </div>
      <div class="stat-row">
        <span class="stat-label">Détection</span>
        <span class="stat-val" id="sDetected">—</span>
      </div>
      <div class="stat-row" style="flex-direction:column;align-items:stretch;gap:3px">
        <div style="display:flex;justify-content:space-between">
          <span class="stat-label">Confiance</span>
          <span class="stat-val" id="sConf">—</span>
        </div>
        <div class="conf-bar"><div class="conf-fill" id="sConfBar" style="width:0%"></div></div>
      </div>
      <div class="stat-row">
        <span class="stat-label">Pos frame</span>
        <span class="stat-val" id="sFramePos">—</span>
      </div>
      <div class="stat-row">
        <span class="stat-label">-> canvas raw</span>
        <span class="stat-val" id="sCanvasRaw">—</span>
      </div>
      <div class="stat-row">
        <span class="stat-label">-> Kalman</span>
        <span class="stat-val yellow" id="sKalman">—</span>
      </div>
      <div class="stat-row">
        <span class="stat-label">But frame</span>
        <span class="stat-val" id="sGoal">—</span>
      </div>
      <div class="stat-row">
        <span class="stat-label">Score</span>
        <span class="stat-val" id="sScore">0 – 0</span>
      </div>
      <div class="sep">Historique buts</div>
      <div class="goal-log" id="goalLog">
        <div style="font-size:11px;color:var(--muted)">Aucun but</div>
      </div>
      <div class="sep">Stats attribuées (1v1)</div>
      <div class="stat-row">
        <span class="stat-label">Possession</span>
        <span class="stat-val" id="sPossBlue" style="color:#42a5f5">—</span>
        <span class="stat-val" style="color:var(--muted);margin:0 4px">/</span>
        <span class="stat-val" id="sPossRed"  style="color:#ef5350">—</span>
      </div>
      <div class="stat-row">
        <span class="stat-label">Buts</span>
        <span class="stat-val" id="sGoalsBlue" style="color:#42a5f5">—</span>
        <span class="stat-val" style="color:var(--muted);margin:0 4px">/</span>
        <span class="stat-val" id="sGoalsRed"  style="color:#ef5350">—</span>
      </div>
      <div class="stat-row">
        <span class="stat-label">Tirs</span>
        <span class="stat-val" id="sShotsBlue" style="color:#42a5f5">—</span>
        <span class="stat-val" style="color:var(--muted);margin:0 4px">/</span>
        <span class="stat-val" id="sShotsRed"  style="color:#ef5350">—</span>
      </div>
      <div class="stat-row">
        <span class="stat-label">Tirs cadrés</span>
        <span class="stat-val" id="sOtBlue" style="color:#42a5f5">—</span>
        <span class="stat-val" style="color:var(--muted);margin:0 4px">/</span>
        <span class="stat-val" id="sOtRed"  style="color:#ef5350">—</span>
      </div>
      <div class="stat-row">
        <span class="stat-label">Arrêts</span>
        <span class="stat-val" id="sSavesBlue" style="color:#42a5f5">—</span>
        <span class="stat-val" style="color:var(--muted);margin:0 4px">/</span>
        <span class="stat-val" id="sSavesRed"  style="color:#ef5350">—</span>
      </div>
      <div class="sep">Contacts (<span id="sContactCount">0</span> détectés)</div>
      <div class="goal-log" id="contactLog" style="max-height:160px"></div>
    </div>
  </div>

</div>

<script>
const CW = {CANVAS_W};
const CH = {CANVAS_H};
const FY0 = {FIELD_Y0};
const FY1 = {FIELD_Y1};
const FH = FY1 - FY0;
const data = {data_json};
const goalTop = {goal_top_json};
const goalBot = {goal_bottom_json};
const contacts = {contacts_json};
const matchStats = {stats_json};
const possession = {poss_json};
const goalRods   = {goal_rods_json};
const ROD_LABELS = {{
  blue_goalkeeper:'Gardien Bleu',  blue_defense:'Défenseur Bleu',
  blue_midfield:'Milieu Bleu',     blue_attack:'Attaquant Bleu',
  red_goalkeeper:'Gardien Rouge',  red_defense:'Défenseur Rouge',
  red_midfield:'Milieu Rouge',     red_midfield2:'Milieu Rouge',
}};

const canvas = document.getElementById('terrainCanvas');
const ctx = canvas.getContext('2d');
let current = 0, playing = false, playTimer = null;

// Fill static attributed stats
document.getElementById('sPossBlue').textContent  = possession.blue + '%';
document.getElementById('sPossRed').textContent   = possession.red  + '%';
document.getElementById('sGoalsBlue').textContent = matchStats.blue?.goals ?? '—';
document.getElementById('sGoalsRed').textContent  = matchStats.red?.goals  ?? '—';
document.getElementById('sShotsBlue').textContent = matchStats.blue?.shots_total ?? '—';
document.getElementById('sShotsRed').textContent  = matchStats.red?.shots_total  ?? '—';
document.getElementById('sOtBlue').textContent    = matchStats.blue?.shots_on_target ?? '—';
document.getElementById('sOtRed').textContent     = matchStats.red?.shots_on_target  ?? '—';
document.getElementById('sSavesBlue').textContent = matchStats.blue?.saves ?? '—';
document.getElementById('sSavesRed').textContent  = matchStats.red?.saves  ?? '—';
document.getElementById('sContactCount').textContent = contacts.length;

// Build contact log entries
(function() {{
  const el = document.getElementById('contactLog');
  if (!contacts.length) {{ el.innerHTML = '<div style="font-size:11px;color:var(--muted)">Aucun contact</div>'; return; }}
  el.innerHTML = contacts.map((c, i) =>
    `<div class="goal-entry ${{c.team}}" style="cursor:pointer;font-size:10px" onclick="seekToContact(${{i}})">
      ${{c.team === 'blue' ? '🔵' : '🔴'}} ${{c.name}} — dev ${{c.deviation}}px (${{(c.t/1000).toFixed(1)}}s)
    </div>`
  ).join('');
}})();

document.getElementById('scrubber').max = data.length - 1;
function fitCanvas() {{
  const wrap = document.getElementById('canvasWrap');
  const ww = wrap.clientWidth - 16;
  const wh = wrap.clientHeight - 16;
  const ratio = CW / CH;
  let w = ww, h = ww / ratio;
  if (h > wh) {{ h = wh; w = h * ratio; }}
  canvas.style.width = w + 'px';
  canvas.style.height = h + 'px';
}}
new ResizeObserver(fitCanvas).observe(document.getElementById('canvasWrap'));
fitCanvas();
const STRIPES = [
  [0/7, 1/7, '#1b6b30', '#175e2a'],
  [1/7, 2/7, '#1e7534', '#1a662e'],
  [2/7, 3/7, '#1b6b30', '#175e2a'],
  [3/7, 4/7, '#216e2e', '#1d622a'],
  [4/7, 5/7, '#1b6b30', '#175e2a'],
  [5/7, 6/7, '#1e7534', '#1a662e'],
  [6/7, 7/7, '#1b6b30', '#175e2a'],
];

function drawField() {{
  ctx.fillStyle = '#0a0a0a';
  ctx.fillRect(0, 0, CW, CH);

  STRIPES.forEach(([f0, f1, c1, c2], i) => {{
    const y0 = FY0 + f0 * FH;
    const y1 = FY0 + f1 * FH;
    const grad = ctx.createLinearGradient(0, y0, 0, y1);
    grad.addColorStop(0,   c1);
    grad.addColorStop(0.5, c2);
    grad.addColorStop(1,   c1);
    ctx.fillStyle = grad;
    ctx.fillRect(0, y0, CW, y1 - y0);
  }});

  ctx.strokeStyle = 'rgba(255,255,255,0.18)';
  ctx.lineWidth = 1;
  ctx.setLineDash([6, 4]);
  for (let i = 1; i < 7; i++) {{
    const y = FY0 + (i / 7) * FH;
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(CW, y); ctx.stroke();
  }}
  ctx.setLineDash([]);

  ctx.strokeStyle = 'rgba(255,255,255,0.7)';
  ctx.lineWidth = 2.5;
  ctx.strokeRect(12, FY0, CW - 24, FH);

  ctx.strokeStyle = 'rgba(255,255,255,0.6)';
  ctx.lineWidth = 2;
  const midY = FY0 + FH / 2;
  ctx.beginPath(); ctx.moveTo(12, midY); ctx.lineTo(CW - 12, midY); ctx.stroke();

  ctx.beginPath(); ctx.arc(CW/2, midY, 44, 0, Math.PI*2); ctx.stroke();
  ctx.beginPath(); ctx.arc(CW/2, midY, 3, 0, Math.PI*2);
  ctx.fillStyle = 'rgba(255,255,255,0.6)'; ctx.fill();

  ctx.strokeStyle = 'rgba(255,255,255,0.8)';
  ctx.lineWidth = 2;
  const gw = CW * (18/68), gx = (CW - gw) / 2;
  ctx.strokeRect(gx, FY0,       gw, 0);
  ctx.strokeRect(gx, FY1,       gw, 0);
  ctx.strokeRect(gx, FY0,       gw, FH*0.05);
  ctx.strokeRect(gx, FY1 - FH*0.05, gw, FH*0.05);
}}

function drawGoals() {{
  if (!goalTop || !goalBot) return;
  const gw = goalTop.x2 - goalTop.x1;

  ctx.fillStyle = 'rgba(21,101,192,0.45)';
  ctx.fillRect(goalTop.x1, goalTop.y1, gw, goalTop.y2 - goalTop.y1);
  ctx.strokeStyle = '#42a5f5'; ctx.lineWidth = 2.5;
  ctx.strokeRect(goalTop.x1, goalTop.y1, gw, goalTop.y2 - goalTop.y1);
  ctx.fillStyle = 'rgba(66,165,245,0.9)';
  ctx.font = 'bold 11px sans-serif'; ctx.textAlign = 'center';
  ctx.fillText('BUT BLEU', CW/2, goalTop.y1 + (goalTop.y2 - goalTop.y1)/2 + 4);

  ctx.fillStyle = 'rgba(229,9,20,0.45)';
  ctx.fillRect(goalBot.x1, goalBot.y1, gw, goalBot.y2 - goalBot.y1);
  ctx.strokeStyle = '#ef5350'; ctx.lineWidth = 2.5;
  ctx.strokeRect(goalBot.x1, goalBot.y1, gw, goalBot.y2 - goalBot.y1);
  ctx.fillStyle = 'rgba(239,83,80,0.9)';
  ctx.fillText('BUT ROUGE', CW/2, goalBot.y1 + (goalBot.y2 - goalBot.y1)/2 + 4);
}}

function drawTrail() {{
  const N = 10;
  for (let i = Math.max(0,current-N); i < current; i++) {{
    const d = data[i]; if (d.kx === null) continue;
    const a = (i - Math.max(0,current-N)) / N;
    ctx.globalAlpha = a * 0.45;
    ctx.beginPath(); ctx.arc(d.kx, d.ky, 5, 0, Math.PI*2);
    ctx.fillStyle='white'; ctx.fill();
  }}
  ctx.globalAlpha = 1;
}}

function drawBall(r) {{
  if (r.kx === null) return;
  ctx.shadowColor='rgba(0,0,0,0.5)'; ctx.shadowBlur=10;
  ctx.beginPath(); ctx.arc(r.kx, r.ky, 11, 0, Math.PI*2);
  ctx.fillStyle='white'; ctx.fill();
  ctx.strokeStyle='#222'; ctx.lineWidth=1.5; ctx.stroke();
  ctx.shadowBlur=0;
}}

function drawContacts(currentTs) {{
  const blueCol  = 'rgba(66,165,245,0.85)';
  const redCol   = 'rgba(239,83,80,0.85)';
  const blueRing = '#42a5f5';
  const redRing  = '#ef5350';
  contacts.forEach((c, i) => {{
    if (c.t > currentTs) return;
    const age = currentTs - c.t;          // ms since contact
    const fade = Math.max(0, 1 - age / 4000);  // fade out over 4 s
    if (fade <= 0) return;
    ctx.globalAlpha = fade * 0.9;
    const col  = c.team === 'blue' ? blueCol  : redCol;
    const ring = c.team === 'blue' ? blueRing : redRing;
    // Size proportional to angle (stronger contact = bigger dot)
    const r = 5 + Math.min(c.deviation / 100, 1) * 8;
    ctx.beginPath(); ctx.arc(c.x, c.y, r, 0, Math.PI * 2);
    ctx.fillStyle = col; ctx.fill();
    ctx.strokeStyle = ring; ctx.lineWidth = 1.5; ctx.stroke();
  }});
  ctx.globalAlpha = 1;
}}

function seekToContact(idx) {{
  if (idx < 0 || idx >= contacts.length) return;
  const ts = contacts[idx].t;
  // find closest frame
  let best = 0, bestDist = Infinity;
  data.forEach((d, i) => {{
    const dist = Math.abs(d.ts - ts);
    if (dist < bestDist) {{ bestDist = dist; best = i; }}
  }});
  goTo(best);
}}

function render(idx) {{
  current = idx;
  const r = data[idx];

  document.getElementById('frameImg').src = 'data:image/jpeg;base64,' + r.frame_b64;
  document.getElementById('frameLabel').textContent = `#${{r.frame_idx}}`;
  document.getElementById('panelVideoTitle').textContent = `Frame vidéo ${{idx+1}} / ${{data.length}} (vidéo frame ${{r.frame_idx}})`;
  document.getElementById('frameCounter').textContent = `${{idx+1}} / ${{data.length}}`;
  document.getElementById('scrubber').value = idx;
  document.getElementById('btnPrev').disabled = idx === 0;
  document.getElementById('btnNext').disabled = idx === data.length - 1;
  document.getElementById('scoreRed').textContent = r.score_red;
  document.getElementById('scoreBlue').textContent = r.score_blue;

  document.getElementById('sFrameIdx').textContent = r.frame_idx;
  document.getElementById('sDetected').innerHTML = r.detected
    ? '<span class="pill pill-green">Oui</span>'
    : '<span class="pill pill-grey">Non</span>';
  const pct = Math.round(r.conf*100);
  document.getElementById('sConf').textContent = pct+'%';
  const bar = document.getElementById('sConfBar');
  bar.style.width = pct + '%';
  bar.style.background = pct > 60 ? 'var(--green)' : pct > 35 ? 'var(--yellow)' : 'var(--red)';
  document.getElementById('sFramePos').textContent = r.cx_frame !== null ? `(${{r.cx_frame|0}},${{r.cy_frame|0}})` : '—';
  document.getElementById('sCanvasRaw').textContent = r.cx_canvas !== null ? `(${{r.cx_canvas|0}},${{r.cy_canvas|0}})` : '—';
  document.getElementById('sKalman').textContent = r.kx !== null ? `(${{r.kx|0}},${{r.ky|0}})` : '—';
  document.getElementById('sScore').textContent = `${{r.score_red}} – ${{r.score_blue}}`;

  if (r.scored) {{
    const c = r.scored === 'red' ? 'pill-red' : 'pill-green';
    document.getElementById('sGoal').innerHTML = `<span class="pill ${{c}}">BUT ${{r.scored.toUpperCase()}}</span>`;
    const flash = document.getElementById('goalFlash');
    flash.textContent = r.scored === 'red' ? '🔴 BUT !' : '🔵 BUT !';
    flash.style.display = 'flex';
    setTimeout(() => flash.style.display = 'none', 900);
  }} else {{
    document.getElementById('sGoal').innerHTML = '<span style="color:var(--muted)">—</span>';
  }}

  ctx.clearRect(0, 0, CW, CH);
  drawField(); drawGoals(); drawContacts(r.ts); drawTrail(); drawBall(r);
}}

function refreshGoalLog() {{
  const el = document.getElementById('goalLog');
  if (!goalRods.length) {{ el.innerHTML='<div style="font-size:11px;color:var(--muted)">Aucun but</div>'; return; }}
  el.innerHTML = goalRods.map(g => {{
    const icon  = g.team === 'red' ? '🔴' : '🔵';
    const label = g.rod ? (ROD_LABELS[g.rod] || g.rod) : g.team;
    return `<div class="goal-entry ${{g.team}}" style="cursor:pointer" onclick="seekToTs(${{g.ts}})">${{icon}} ${{label}} (frame ${{g.frame_idx}})</div>`;
  }}).join('');
}}

function seekToTs(ts) {{
  let best = 0, bestDist = Infinity;
  data.forEach((d, i) => {{ const dist = Math.abs(d.ts - ts); if (dist < bestDist) {{ bestDist = dist; best = i; }} }});
  goTo(best);
}}

function navigate(d) {{ goTo(Math.max(0, Math.min(data.length - 1, current + d))); }}
function goTo(idx) {{ render(Math.max(0, Math.min(data.length - 1, idx))); }}
function togglePlay() {{
  playing = !playing;
  document.getElementById('btnPlay').textContent = playing ? '⏸ Pause' : '▶ Play';
  if (playing) playNext(); else clearTimeout(playTimer);
}}
function playNext() {{
  if (!playing) return;
  if (current >= data.length - 1) {{ playing = false; document.getElementById('btnPlay').textContent = '▶ Play'; return; }}
  navigate(1); playTimer = setTimeout(playNext, 80);
}}
document.addEventListener('keydown', e => {{
  if (e.key === 'ArrowRight') navigate(1);
  else if (e.key === 'ArrowLeft') navigate(-1);
  else if (e.key === ' ') {{ e.preventDefault(); togglePlay(); }}
}});
refreshGoalLog();
render(0);
</script>
</body>
</html>"""

    out = os.path.join(os.path.dirname(__file__), "..", "frontend", "public", "test_pipeline.html")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)


if __name__ == "__main__":
    main()