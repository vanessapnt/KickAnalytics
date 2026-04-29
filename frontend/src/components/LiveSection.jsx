import { useRef, useEffect } from 'react';

// ─── Canvas field constants (canvas is 450×880) ────────────────────────────
const CW = 450, CH = 880;
const FIELD_Y0 = Math.round(CH * 40 / 880);
const FIELD_Y1 = CH - FIELD_Y0;
const FIELD_H  = FIELD_Y1 - FIELD_Y0;
const GOAL_X1  = Math.round(CW * (25 / 68));
const GOAL_X2  = Math.round(CW * (43 / 68));
const STRIPES  = [
  ['#1b6b30','#175e2a'], ['#1e7534','#1a662e'], ['#1b6b30','#175e2a'],
  ['#216e2e','#1d622a'], ['#1b6b30','#175e2a'], ['#1e7534','#1a662e'],
  ['#1b6b30','#175e2a'],
];
const ROD_LABELS = {
  blue_goalkeeper: 'Blue Goalkeeper', blue_defense:  'Blue Defender',
  blue_midfield:   'Blue Midfielder', blue_attack:   'Blue Forward',
  red_goalkeeper:  'Red Goalkeeper',  red_defense:   'Red Defender',
  red_midfield:    'Red Midfielder',  red_midfield2: 'Red Midfielder',
};

function drawField(ctx) {
  ctx.fillStyle = '#0a0a0a';
  ctx.fillRect(0, 0, CW, CH);
  STRIPES.forEach(([c1, c2], i) => {
    const y0 = FIELD_Y0 + (i / 7) * FIELD_H, y1 = FIELD_Y0 + ((i + 1) / 7) * FIELD_H;
    const g = ctx.createLinearGradient(0, y0, 0, y1);
    g.addColorStop(0, c1); g.addColorStop(0.5, c2); g.addColorStop(1, c1);
    ctx.fillStyle = g; ctx.fillRect(0, y0, CW, y1 - y0);
  });
  ctx.strokeStyle = 'rgba(255,255,255,0.18)'; ctx.lineWidth = 1; ctx.setLineDash([6, 4]);
  for (let i = 1; i < 7; i++) {
    const y = FIELD_Y0 + (i / 7) * FIELD_H;
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(CW, y); ctx.stroke();
  }
  ctx.setLineDash([]);
  ctx.strokeStyle = 'rgba(255,255,255,0.75)'; ctx.lineWidth = 2.5;
  ctx.strokeRect(12, FIELD_Y0, CW - 24, FIELD_H);
  ctx.strokeStyle = 'rgba(255,255,255,0.6)'; ctx.lineWidth = 2;
  const midY = FIELD_Y0 + FIELD_H / 2;
  ctx.beginPath(); ctx.moveTo(12, midY); ctx.lineTo(CW - 12, midY); ctx.stroke();
  ctx.beginPath(); ctx.arc(CW / 2, midY, 44, 0, Math.PI * 2); ctx.stroke();
  ctx.beginPath(); ctx.arc(CW / 2, midY, 3, 0, Math.PI * 2);
  ctx.fillStyle = 'rgba(255,255,255,0.6)'; ctx.fill();
  ctx.fillStyle = 'rgba(21,101,192,0.4)';
  ctx.fillRect(GOAL_X1, 0, GOAL_X2 - GOAL_X1, FIELD_Y0);
  ctx.strokeStyle = '#42a5f5'; ctx.lineWidth = 2;
  ctx.strokeRect(GOAL_X1, 0, GOAL_X2 - GOAL_X1, FIELD_Y0);
  ctx.fillStyle = 'rgba(229,9,20,0.4)';
  ctx.fillRect(GOAL_X1, FIELD_Y1, GOAL_X2 - GOAL_X1, CH - FIELD_Y1);
  ctx.strokeStyle = '#ef5350'; ctx.lineWidth = 2;
  ctx.strokeRect(GOAL_X1, FIELD_Y1, GOAL_X2 - GOAL_X1, CH - FIELD_Y1);
}

// Props:
//   scoreRed, scoreBlue, liveStatus {text, type}, latency, ballPos {x,y}|null
//   showPauseOverlay
//   goalFlash: { team, rod, key } | null   — key changes on each goal to re-trigger the effect
//   replayFrames: string[] | null          — set by IndexPage when a replay arrives
export default function LiveSection({ scoreRed, scoreBlue, liveStatus, latency, ballPos, showPauseOverlay, goalFlash, replayFrames }) {
  const canvasRef        = useRef(null);
  const ctxRef           = useRef(null);
  const replayOverlayRef = useRef(null);
  const replayImgRef     = useRef(null);
  const goalFlashRef     = useRef(null);
  const goalTimerRef     = useRef(null);

  // Initial field draw
  useEffect(() => {
    if (canvasRef.current) { ctxRef.current = canvasRef.current.getContext('2d'); drawField(ctxRef.current); }
  }, []);

  // Redraw on ball position change
  useEffect(() => {
    const ctx = ctxRef.current;
    if (!ctx) return;
    if (!ballPos) { drawField(ctx); return; }
    drawField(ctx);
    const x = ballPos.x * CW, y = FIELD_Y0 + ballPos.y * FIELD_H;
    ctx.shadowColor = 'rgba(0,0,0,0.4)'; ctx.shadowBlur = 12;
    ctx.beginPath(); ctx.arc(x, y, 11, 0, Math.PI * 2);
    ctx.fillStyle = 'white'; ctx.fill();
    ctx.strokeStyle = '#222'; ctx.lineWidth = 1.5; ctx.stroke();
    ctx.shadowBlur = 0;
  }, [ballPos]);

  // Goal flash — imperatively animated to avoid re-renders during the animation
  useEffect(() => {
    if (!goalFlash || !goalFlashRef.current) return;
    const el = goalFlashRef.current;
    if (goalTimerRef.current) clearTimeout(goalTimerRef.current);
    el.className = 'goal-flash ' + (goalFlash.team === 'red' ? 'red' : 'blue');
    el.querySelector('.goal-flash-title').textContent = goalFlash.team === 'red' ? '🔴 GOAL!' : '🔵 GOAL!';
    el.querySelector('.goal-flash-rod').textContent   = goalFlash.rod ? (ROD_LABELS[goalFlash.rod] || goalFlash.rod) : '';
    el.style.display = 'flex';
    goalTimerRef.current = setTimeout(() => { el.style.display = 'none'; }, 2500);
  }, [goalFlash?.key]); // eslint-disable-line react-hooks/exhaustive-deps

  // Replay animation — imperatively animated to avoid re-renders per frame (80ms cadence)
  useEffect(() => {
    if (!replayFrames || !replayOverlayRef.current || !replayImgRef.current) return;
    const ov = replayOverlayRef.current, img = replayImgRef.current;
    ov.style.display = 'block';
    let i = 0; const off = new Image();
    function next() {
      if (i >= replayFrames.length) { ov.style.display = 'none'; return; }
      off.onload = () => { img.src = off.src; setTimeout(next, 80); };
      off.src = replayFrames[i++];
    }
    next();
  }, [replayFrames]);

  const total  = scoreRed + scoreBlue;
  const domPct = total === 0 ? 50 : Math.round(scoreRed / total * 100);

  return (
    <div className="section active">
      <div className="page-content">
        <div className="live-layout">

          <div className="live-left">
            <div className="field-card">
              <canvas ref={canvasRef} id="terrain" width={CW} height={CH}></canvas>
              <div className="replay-overlay" ref={replayOverlayRef}>
                <div className="replay-label">REPLAY</div>
                <img ref={replayImgRef} alt="" />
              </div>
              <div style={{
                display: showPauseOverlay ? 'flex' : 'none',
                position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.65)', zIndex: 10,
                flexDirection: 'column', alignItems: 'center', justifyContent: 'center', borderRadius: '12px',
              }}>
                <div style={{ fontSize: '52px', animation: 'pausePulse 1.5s ease-in-out infinite' }}>⏸</div>
                <div style={{ color: 'white', fontWeight: 900, fontSize: '20px', marginTop: '10px', letterSpacing: '1px' }}>MATCH PAUSED</div>
                <div style={{ color: '#ccc', fontSize: '13px', marginTop: '6px' }}>Camera disconnected, reconnecting…</div>
              </div>
              <div className="goal-flash" ref={goalFlashRef}>
                <div className="goal-flash-title">GOAL!</div>
                <div className="goal-flash-rod"></div>
              </div>
            </div>

            <div className="stats-grid">
              <div className="stat-card"><div className="stat-val">{ballPos ? ballPos.x.toFixed(2) : '—'}</div><div className="stat-lbl">X</div></div>
              <div className="stat-card"><div className="stat-val">{ballPos ? ballPos.y.toFixed(2) : '—'}</div><div className="stat-lbl">Y</div></div>
            </div>
            <div className="latency-card">
              <span className="lbl">Latency</span>
              <span className="val">{latency}</span>
            </div>
          </div>

          <div className="live-right">
            <div className="match-card">
              <div className="match-meta"><span>Foosball, official match</span><span>Live</span></div>
              <div className="match-score">
                <div className="team"><div className="team-badge red">🔴</div><span className="team-name">Red</span></div>
                <div className="score-center">
                  <span className="score-num">{scoreRed}</span>
                  <span className="score-sep">-</span>
                  <span className="score-num">{scoreBlue}</span>
                </div>
                <div className="team"><div className="team-badge blue">🔵</div><span className="team-name">Blue</span></div>
              </div>
              <div className="dom-bar"><div className="dom-fill" style={{ width: domPct + '%' }}></div></div>
              <div className="dom-labels"><span>{domPct}%</span><span>{100 - domPct}%</span></div>
              <div><span className={`status-tag${liveStatus.type ? ' ' + liveStatus.type : ''}`}>{liveStatus.text}</span></div>
            </div>
          </div>

        </div>
      </div>
    </div>
  );
}
