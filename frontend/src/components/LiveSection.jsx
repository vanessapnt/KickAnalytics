import { useRef, useEffect, useState, useCallback } from 'react';

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

function MiniAvatar({ player, alignRight }) {
  const letter = (player.display_name || player.username || '?')[0].toUpperCase();
  return (
    <div className={`lstats-av-wrap${alignRight ? ' right' : ''}`}>
      <div className={`lstats-av${alignRight ? ' blue' : ' red'}`}>
        {player.avatar
          ? <img src={player.avatar} className="lstats-av-img" alt="" />
          : letter}
      </div>
      <div className="lstats-av-name">{player.display_name || player.username}</div>
    </div>
  );
}

function PossRing({ red }) {
  const R = 24, circ = 2 * Math.PI * R, gap = 4;
  const redLen = (red / 100) * circ;
  return (
    <svg width="64" height="64" viewBox="0 0 64 64" style={{ display: 'block', flexShrink: 0 }}>
      <circle cx="32" cy="32" r={R} fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth="8" />
      <circle cx="32" cy="32" r={R} fill="none" stroke="#c0392b" strokeWidth="8"
        strokeDasharray={`${Math.max(0, redLen - gap / 2)} ${circ}`}
        transform="rotate(-90 32 32)" />
      <circle cx="32" cy="32" r={R} fill="none" stroke="#1565c0" strokeWidth="8"
        strokeDasharray={`${Math.max(0, circ - redLen - gap / 2)} ${circ}`}
        strokeDashoffset={-(redLen + gap / 2)}
        transform="rotate(-90 32 32)" />
    </svg>
  );
}

function StatSplit({ label, red, blue }) {
  const total = red + blue;
  const redPct = total === 0 ? 50 : Math.round((red / total) * 100);
  return (
    <div className="lstat-split">
      <div className="lstat-split-row">
        <span className="lstat-n lstat-n-red">{red}</span>
        <span className="lstat-split-lbl">{label}</span>
        <span className="lstat-n lstat-n-blue">{blue}</span>
      </div>
      <div className="lstat-bar">
        <div className="lstat-bar-red" style={{ width: redPct + '%' }} />
        <div className="lstat-bar-blue" style={{ width: (100 - redPct) + '%' }} />
      </div>
    </div>
  );
}

export default function LiveSection({ scoreRed, scoreBlue, liveStatus, latency, ballPos, showPauseOverlay, goalFlash, replayFrames, goals, matchPlayers, liveStats, contactCounts, recentContacts, matchStart, onBack }) {
  const canvasRef          = useRef(null);
  const ctxRef             = useRef(null);
  const replayWrapRef      = useRef(null);
  const replayImgRef       = useRef(null);
  const goalFlashRef       = useRef(null);
  const goalTimerRef       = useRef(null);
  const trailRef           = useRef([]);
  const recentContactsRef  = useRef([]);
  const [showRotate, setShowRotate] = useState(false);
  const [hasReplay, setHasReplay]   = useState(false);
  const [elapsed, setElapsed]       = useState(0);

  useEffect(() => { recentContactsRef.current = recentContacts || []; }, [recentContacts]);

  const redContacts   = contactCounts?.red  ?? 0;
  const blueContacts  = contactCounts?.blue ?? 0;
  const totalContacts = redContacts + blueContacts;
  const possession = totalContacts === 0
    ? { red: 50, blue: 50 }
    : { red: Math.round(redContacts / totalContacts * 100), blue: Math.round(blueContacts / totalContacts * 100) };

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

    const now = Date.now();
    recentContactsRef.current.forEach(c => {
      const age = now - c.t;
      const fade = Math.max(0, 1 - age / 4000);
      if (fade <= 0) return;
      const ccx = FIELD_X0 + c.y * FIELD_W;
      const ccy = c.x * CH;
      const r = 5 + Math.min((c.deviation || 0) / 100, 1) * 8;
      ctx.globalAlpha = fade * 0.88;
      ctx.beginPath(); ctx.arc(ccx, ccy, r, 0, Math.PI * 2);
      ctx.fillStyle   = c.team === 'blue' ? 'rgba(66,165,245,0.85)' : 'rgba(239,83,80,0.85)';
      ctx.strokeStyle = c.team === 'blue' ? '#42a5f5' : '#ef5350';
      ctx.fill(); ctx.lineWidth = 1.5; ctx.stroke();
    });
    ctx.globalAlpha = 1;

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

  useEffect(() => {
    if (!matchStart) { setElapsed(0); return; }
    setElapsed(Math.floor((Date.now() - matchStart) / 1000));
    const id = setInterval(() => setElapsed(Math.floor((Date.now() - matchStart) / 1000)), 1000);
    return () => clearInterval(id);
  }, [matchStart]);

  const fmtTime = useCallback((s) => {
    const m = Math.floor(s / 60).toString().padStart(2, '0');
    const sec = (s % 60).toString().padStart(2, '0');
    return `${m}:${sec}`;
  }, []);

  const redName  = matchPlayers?.red?.map(p => p.display_name || p.username).join(' & ') || 'Red';
  const blueName = matchPlayers?.blue?.map(p => p.display_name || p.username).join(' & ') || 'Blue';

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

      <div className="live-topbar">
        <div className="ltb-logo">KickAnalytics</div>

        <div className="ltb-match">
          <div className="ltb-scoreline">
            <span className="ltb-name ltb-name-red">{redName}</span>
            <div className="ltb-score">
              <span className="ltb-num">{scoreRed}</span>
              <span className="ltb-sep">–</span>
              <span className="ltb-num">{scoreBlue}</span>
            </div>
            <span className="ltb-name ltb-name-blue">{blueName}</span>
            {matchStart && <span className="ltb-timer">{fmtTime(elapsed)}</span>}
          </div>
          {goals.length > 0 && (
            <div className="ltb-goals">
              {goals.map((g, i) => (
                <span key={i} className={`ltb-goal ltb-goal-${g.team}`}>⚽ {g.scorer} {g.minute}'</span>
              ))}
            </div>
          )}
        </div>

        <button className="ltb-back" onClick={onBack}>←</button>
      </div>

      <div className="live-body">

        <div className="live-stats-col">
          <div className="live-panel lstats-panel">
            <div className="lstats-header">
              <span className="lstats-dot" />
              LIVE STATISTIQUES
            </div>

            {matchPlayers && (matchPlayers.red.length > 0 || matchPlayers.blue.length > 0) ? (
              <div className="lstats-players">
                <div className="lstats-team">
                  {matchPlayers.red.map(p => <MiniAvatar key={p.username} player={p} />)}
                </div>
                <div className="lstats-team">
                  {matchPlayers.blue.map(p => <MiniAvatar key={p.username} player={p} alignRight />)}
                </div>
              </div>
            ) : (
              <div className="lstats-no-match">Aucun match en cours</div>
            )}

            <div className="lstats-divider" />

            <div className="lstats-poss-row">
              <div className="lstats-poss-side">
                <div className="lstats-poss-val lstats-poss-red">{possession.red}%</div>
                <div className="lstats-poss-team-lbl">Rouge</div>
              </div>
              <PossRing red={possession.red} />
              <div className="lstats-poss-side right">
                <div className="lstats-poss-val lstats-poss-blue">{possession.blue}%</div>
                <div className="lstats-poss-team-lbl">Bleu</div>
              </div>
            </div>
            <div className="lstats-poss-lbl">Possession</div>

            <div className="lstats-divider" />

            <div className="lstats-stats">
              <StatSplit label="Buts" red={scoreRed} blue={scoreBlue} />
              <StatSplit label="Contacts" red={redContacts} blue={totalContacts - redContacts} />
            </div>

            {recentContacts && recentContacts.length > 0 && (
              <>
                <div className="lstats-divider" />
                <div className="lstats-contacts">
                  {[...recentContacts].reverse().map((c, i) => (
                    <div key={i} className={`lstats-contact ${c.team}`}>
                      <span className="lstats-contact-dot" />
                      <span className="lstats-contact-rod">{c.rod.replace('_', ' ')}</span>
                      <span className="lstats-contact-dev">{c.deviation}px</span>
                    </div>
                  ))}
                </div>
              </>
            )}
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
                {matchPlayers.red.map(p => <MiniAvatar key={p.username} player={p} />)}
                <div className="comp-sep" />
                <div className="comp-team-bar">🔵 Blue</div>
                {matchPlayers.blue.map(p => <MiniAvatar key={p.username} player={p} alignRight />)}
              </>
            ) : (
              <div className="comp-empty">No match in progress</div>
            )}
          </div>
        </div>

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
