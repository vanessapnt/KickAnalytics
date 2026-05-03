import { useRef, useEffect, useState } from 'react';

const CW = 880, CH = 450;
const GOAL_DEPTH = 40;
const FIELD_X0   = GOAL_DEPTH;
const FIELD_X1   = CW - GOAL_DEPTH;
const FIELD_W    = FIELD_X1 - FIELD_X0;
const GOAL_Y1    = Math.round(CH * (25 / 68));
const GOAL_Y2    = Math.round(CH * (43 / 68));
const TRAIL_LEN  = 10;

const STRIPES = [
  ['#1d222c','#1d222c'], ['#0e1520','#0e1520'], ['#1d222c','#1d222c'],
  ['#0e1520','#0e1520'], ['#1d222c','#1d222c'], ['#0e1520','#0e1520'],
  ['#1d222c','#1d222c'],
];

const ROD_LABELS = {
  blue_goalkeeper: 'Blue Goalkeeper', blue_defense:  'Blue Defender',
  blue_midfield:   'Blue Midfielder', blue_attack:   'Blue Forward',
  red_goalkeeper:  'Red Goalkeeper',  red_defense:   'Red Defender',
  red_midfield:    'Red Midfielder',  red_midfield2: 'Red Midfielder',
};

function drawField(ctx) {
  ctx.fillStyle = '#0a111c';
  ctx.fillRect(0, 0, CW, CH);

  STRIPES.forEach(([c1, c2], i) => {
    const x0 = FIELD_X0 + (i / 7) * FIELD_W;
    const x1 = FIELD_X0 + ((i + 1) / 7) * FIELD_W;
    const g = ctx.createLinearGradient(x0, 0, x1, 0);
    g.addColorStop(0, c1); g.addColorStop(0.5, c2); g.addColorStop(1, c1);
    ctx.fillStyle = g; ctx.fillRect(x0, 0, x1 - x0, CH);
  });

  ctx.strokeStyle = 'rgba(255,255,255,0.22)'; ctx.lineWidth = 1; ctx.setLineDash([6, 4]);
  for (let i = 1; i < 7; i++) {
    const x = FIELD_X0 + (i / 7) * FIELD_W;
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, CH); ctx.stroke();
  }
  ctx.setLineDash([]);

  ctx.strokeStyle = 'white'; ctx.lineWidth = 2.5;
  ctx.strokeRect(FIELD_X0, 10, FIELD_W, CH - 20);

  ctx.strokeStyle = 'white'; ctx.lineWidth = 2;
  const midX = FIELD_X0 + FIELD_W / 2;
  ctx.beginPath(); ctx.moveTo(midX, 10); ctx.lineTo(midX, CH - 10); ctx.stroke();
  ctx.beginPath(); ctx.arc(midX, CH / 2, 44, 0, Math.PI * 2); ctx.stroke();
  ctx.beginPath(); ctx.arc(midX, CH / 2, 3, 0, Math.PI * 2);
  ctx.fillStyle = 'white'; ctx.fill();

  ctx.strokeStyle = 'white'; ctx.lineWidth = 2;
  const surfW = FIELD_W * 0.06, surfH = CH * (18 / 68), surfY = (CH - surfH) / 2;
  ctx.strokeRect(FIELD_X0, surfY, surfW, surfH);
  ctx.strokeRect(FIELD_X1 - surfW, surfY, surfW, surfH);

  const goalH = GOAL_Y2 - GOAL_Y1;

  ctx.fillStyle = 'rgba(21,101,192,0.45)';
  ctx.fillRect(0, GOAL_Y1, GOAL_DEPTH, goalH);
  ctx.strokeStyle = '#42a5f5'; ctx.lineWidth = 2.5;
  ctx.strokeRect(0, GOAL_Y1, GOAL_DEPTH, goalH);
  ctx.fillStyle = 'rgba(66,165,245,0.9)';
  ctx.font = 'bold 10px sans-serif'; ctx.textAlign = 'center';
  ctx.save(); ctx.translate(GOAL_DEPTH / 2, CH / 2); ctx.rotate(-Math.PI / 2);
  ctx.fillText('BUT BLEU', 0, 4); ctx.restore();

  ctx.fillStyle = 'rgba(229,9,20,0.45)';
  ctx.fillRect(FIELD_X1, GOAL_Y1, GOAL_DEPTH, goalH);
  ctx.strokeStyle = '#ef5350'; ctx.lineWidth = 2.5;
  ctx.strokeRect(FIELD_X1, GOAL_Y1, GOAL_DEPTH, goalH);
  ctx.fillStyle = 'rgba(239,83,80,0.9)';
  ctx.save(); ctx.translate(FIELD_X1 + GOAL_DEPTH / 2, CH / 2); ctx.rotate(Math.PI / 2);
  ctx.fillText('BUT ROUGE', 0, 4); ctx.restore();
}

function PlayerCard({ player }) {
  const letter = (player.display_name || player.username || '?')[0].toUpperCase();
  return (
    <div className="comp-player">
      <div className="comp-av">
        {player.avatar
          ? <img src={player.avatar} className="comp-av-img" alt="" />
          : letter}
      </div>
      <div className="comp-info">
        <div className="comp-uname">@{player.username}</div>
        <div className="comp-elo-val">{player.elo} ELO</div>
      </div>
      <div className="comp-deltas">
        <span className="comp-delta win">{player.win_delta >= 0 ? '+' : ''}{player.win_delta}</span>
        <span className="comp-delta loss">{player.loss_delta}</span>
      </div>
    </div>
  );
}

export default function LiveSection({ scoreRed, scoreBlue, liveStatus, latency, ballPos, showPauseOverlay, goalFlash, replayFrames, goals, matchPlayers }) {
  const canvasRef     = useRef(null);
  const ctxRef        = useRef(null);
  const replayWrapRef = useRef(null);
  const replayImgRef  = useRef(null);
  const goalFlashRef  = useRef(null);
  const goalTimerRef  = useRef(null);
  const trailRef      = useRef([]);
  const [showRotate, setShowRotate] = useState(false);
  const [hasReplay, setHasReplay]   = useState(false);

  useEffect(() => {
    if (window.innerHeight > window.innerWidth) {
      setShowRotate(true);
      const t = setTimeout(() => setShowRotate(false), 2000);
      return () => clearTimeout(t);
    }
  }, []);

  useEffect(() => {
    if (canvasRef.current) {
      ctxRef.current = canvasRef.current.getContext('2d');
      drawField(ctxRef.current);
    }
  }, []);

  useEffect(() => {
    const ctx = ctxRef.current;
    if (!ctx) return;
    if (!ballPos) { trailRef.current = []; drawField(ctx); return; }
    const cx = FIELD_X0 + ballPos.y * FIELD_W;
    const cy = ballPos.x * CH;
    trailRef.current = [...trailRef.current.slice(-(TRAIL_LEN - 1)), { x: cx, y: cy }];
    drawField(ctx);
    const trail = trailRef.current;
    for (let i = 0; i < trail.length - 1; i++) {
      ctx.globalAlpha = ((i + 1) / trail.length) * 0.45;
      ctx.beginPath(); ctx.arc(trail[i].x, trail[i].y, 5, 0, Math.PI * 2);
      ctx.fillStyle = 'white'; ctx.fill();
    }
    ctx.globalAlpha = 1;
    ctx.shadowColor = 'rgba(0,0,0,0.5)'; ctx.shadowBlur = 10;
    ctx.beginPath(); ctx.arc(cx, cy, 11, 0, Math.PI * 2);
    ctx.fillStyle = 'white'; ctx.fill();
    ctx.strokeStyle = '#222'; ctx.lineWidth = 1.5; ctx.stroke();
    ctx.shadowBlur = 0;
  }, [ballPos]);

  useEffect(() => {
    if (!goalFlash || !goalFlashRef.current) return;
    const el = goalFlashRef.current;
    if (goalTimerRef.current) clearTimeout(goalTimerRef.current);
    el.className = 'goal-flash ' + (goalFlash.team === 'red' ? 'red' : 'blue');
    el.querySelector('.goal-flash-title').textContent = goalFlash.team === 'red' ? '🔴 GOAL!' : '🔵 GOAL!';
    el.querySelector('.goal-flash-rod').textContent   = goalFlash.rod ? (ROD_LABELS[goalFlash.rod] || goalFlash.rod) : '';
    el.style.display = 'flex';
    goalTimerRef.current = setTimeout(() => { el.style.display = 'none'; }, 2500);
  }, [goalFlash?.key]);

  useEffect(() => {
    if (!replayFrames || !replayWrapRef.current || !replayImgRef.current) return;
    const ov = replayWrapRef.current, img = replayImgRef.current;
    setHasReplay(true);
    ov.style.display = 'flex';
    let i = 0; const off = new Image();
    function next() {
      if (i >= replayFrames.length) {
        setTimeout(() => { ov.style.display = 'none'; setHasReplay(false); }, 500);
        return;
      }
      off.onload = () => { img.src = off.src; setTimeout(next, 80); };
      off.src = replayFrames[i++];
    }
    next();
  }, [replayFrames]);

  const total   = scoreRed + scoreBlue;
  const domPct  = total === 0 ? 50 : Math.round(scoreRed / total * 100);
  const redGoals  = (goals || []).filter(g => g.team === 'red');
  const blueGoals = (goals || []).filter(g => g.team === 'blue');

  return (
    <div className="live-full">

      {showRotate && (
        <div className="live-rotate-overlay">
          <div className="live-rotate-icon">📱</div>
          <div className="live-rotate-text">Rotate your phone</div>
        </div>
      )}

      <div className="live-score-header">
        <div className="lsh-team">
          <div className="team-badge red">🔴</div>
          <div className="lsh-team-info">
            <span className="lsh-team-name">Red</span>
            <div className="lsh-goals">
              {redGoals.map((g, i) => <span key={i} className="lsh-goal-min">⚽ {g.minute}'</span>)}
            </div>
          </div>
        </div>

        <div className="lsh-center">
          <div className="lsh-score">
            <span className="lsh-num">{scoreRed}</span>
            <span className="lsh-sep">–</span>
            <span className="lsh-num">{scoreBlue}</span>
          </div>
          <div className="lsh-dom-bar">
            <div className="lsh-dom-fill" style={{ width: domPct + '%' }} />
          </div>
          <div className="lsh-footer">
            <span className={`status-tag${liveStatus.type ? ' ' + liveStatus.type : ''}`}>{liveStatus.text}</span>
            <span className="lsh-latency">{latency}</span>
          </div>
        </div>

        <div className="lsh-team lsh-team-right">
          <div className="lsh-team-info right">
            <span className="lsh-team-name">Blue</span>
            <div className="lsh-goals">
              {blueGoals.map((g, i) => <span key={i} className="lsh-goal-min">⚽ {g.minute}'</span>)}
            </div>
          </div>
          <div className="team-badge blue">🔵</div>
        </div>
      </div>

      <div className="live-body">

        <div className="live-stats-col">
          <div className="live-panel" style={{ flex: 1 }}>
            <div className="live-panel-title">Match Stats</div>
            <div className="live-stat-row">
              <span className="live-stat-label">🔴 Goals</span>
              <span className="live-stat-val">{scoreRed}</span>
            </div>
            <div className="live-stat-row">
              <span className="live-stat-label">🔵 Goals</span>
              <span className="live-stat-val">{scoreBlue}</span>
            </div>
            <div className="live-stat-row">
              <span className="live-stat-label">Red possession</span>
              <span className="live-stat-val">{domPct}%</span>
            </div>
            <div className="live-stat-row">
              <span className="live-stat-label">Blue possession</span>
              <span className="live-stat-val">{100 - domPct}%</span>
            </div>
            <div className="live-stat-row">
              <span className="live-stat-label">Latency</span>
              <span className="live-stat-val">{latency}</span>
            </div>
          </div>
        </div>

        <div className="live-terrain-col">
          <div className="live-canvas-wrap">
            <canvas ref={canvasRef} id="terrain" width={CW} height={CH} />
            <div style={{
              display: showPauseOverlay ? 'flex' : 'none',
              position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.65)', zIndex: 10,
              flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
            }}>
              <div style={{ fontSize: '52px', animation: 'pausePulse 1.5s ease-in-out infinite' }}>⏸</div>
              <div style={{ color: 'white', fontWeight: 900, fontSize: '20px', marginTop: '10px' }}>MATCH PAUSED</div>
              <div style={{ color: '#ccc', fontSize: '13px', marginTop: '6px' }}>Camera disconnected, reconnecting…</div>
            </div>
            <div className="goal-flash" ref={goalFlashRef}>
              <div className="goal-flash-title">GOAL!</div>
              <div className="goal-flash-rod"></div>
            </div>
          </div>
        </div>

        <div className="live-composition-col">
          <div className="live-panel" style={{ flex: 1, overflowY: 'auto' }}>
            <div className="live-panel-title">Composition</div>
            {matchPlayers && (matchPlayers.red.length > 0 || matchPlayers.blue.length > 0) ? (
              <>
                <div className="comp-team-bar">🔴 Red</div>
                {matchPlayers.red.map(p => <PlayerCard key={p.username} player={p} />)}
                <div className="comp-sep" />
                <div className="comp-team-bar">🔵 Blue</div>
                {matchPlayers.blue.map(p => <PlayerCard key={p.username} player={p} />)}
              </>
            ) : (
              <div className="comp-empty">No match in progress</div>
            )}
          </div>
        </div>

        {/* Row 2 - Col 1: Reactions */}
        <div className="live-reactions-col">
          <div className="live-panel" style={{ flex: 1 }}>
            <div className="live-panel-title">Reactions</div>
            <div style={{ textAlign: 'center', color: 'var(--muted)', fontSize: '11px', padding: '12px 0', fontWeight: 600 }}>
              Coming soon
            </div>
          </div>
        </div>

        <div className="live-replay-col">
          <div className="live-replay-section">
            <div className="replay-idle-screen" style={{ display: hasReplay ? 'none' : 'flex' }}>
              <span className="replay-idle-icon">📺</span>
              <span className="replay-idle-text">Instant Replay</span>
            </div>
            <div className="live-replay-active" ref={replayWrapRef} style={{ display: 'none' }}>
              <div className="replay-label">REPLAY</div>
              <img ref={replayImgRef} alt="" />
            </div>
          </div>
        </div>

        <div className="live-side-col">
          <div className="live-panel" style={{ flex: 1, overflowY: 'auto' }}>
            <div className="live-panel-title">Live</div>
            <div style={{ textAlign: 'center', color: 'var(--muted)', fontSize: '11px', padding: '12px 0', fontWeight: 600 }}>
              Coming soon
            </div>
          </div>
        </div>

      </div>
    </div>
  );
}
