import { useState, useEffect, useRef, useCallback } from 'react';

const STRIPES = [
  [0/7, 1/7, '#1d222c', '#1d222c'],
  [1/7, 2/7, '#0e1520', '#0e1520'],
  [2/7, 3/7, '#1d222c', '#1d222c'],
  [3/7, 4/7, '#0e1520', '#0e1520'],
  [4/7, 5/7, '#1d222c', '#1d222c'],
  [5/7, 6/7, '#0e1520', '#0e1520'],
  [6/7, 7/7, '#1d222c', '#1d222c'],
];

const ROD_LABELS = {
  blue_goalkeeper: 'Gardien Bleu',  blue_defense: 'Défenseur Bleu',
  blue_midfield:   'Milieu Bleu',   blue_attack:  'Attaquant Bleu',
  red_goalkeeper:  'Gardien Rouge', red_defense:  'Défenseur Rouge',
  red_midfield:    'Milieu Rouge',  red_midfield2: 'Milieu Rouge',
};

export default function TestPipelinePage() {
  const [frames, setFrames]   = useState([]);
  const [meta, setMeta]       = useState(null);
  const [current, setCurrent] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const [progress, setProgress] = useState(0);

  const canvasRef  = useRef();
  const wrapRef    = useRef();
  const playRef    = useRef();
  const framesRef  = useRef([]);
  const metaRef    = useRef(null);

  useEffect(() => { framesRef.current = frames; }, [frames]);
  useEffect(() => { metaRef.current = meta; }, [meta]);

  useEffect(() => {
    const fetchWithProgress = async (url, onProgress) => {
      const res = await fetch(url);
      if (!res.ok) throw new Error(`${url.split('/').pop()} introuvable`);
      const total = parseInt(res.headers.get('content-length') || '0', 10);
      const reader = res.body.getReader();
      const chunks = [];
      let loaded = 0;
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        chunks.push(value);
        loaded += value.length;
        if (total) onProgress(Math.round((loaded / total) * 100));
      }
      const buf = new Uint8Array(loaded);
      let pos = 0;
      for (const c of chunks) { buf.set(c, pos); pos += c.length; }
      return JSON.parse(new TextDecoder().decode(buf));
    };

    const BASE = import.meta.env.DEV
      ? '/pipeline_data'
      : 'https://api.kickanalytics.live/pipeline-data';
    Promise.all([
      fetchWithProgress(`${BASE}/frames.json`, p => setProgress(Math.round(p * 0.95))),
      fetch(`${BASE}/meta.json`).then(r => { if (!r.ok) throw new Error('meta.json introuvable'); return r.json(); }),
    ]).then(([f, m]) => {
      setProgress(100);
      setFrames(f);
      setMeta(m);
      setLoading(false);
    }).catch(err => {
      setLoadError(err.message);
      setLoading(false);
    });
  }, []);

  useEffect(() => {
    const wrap = wrapRef.current;
    if (!wrap) return;
    const fit = () => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      const { CW, CH } = metaRef.current?.canvas ?? { CW: 450, CH: 880 };
      const ww = wrap.clientWidth - 16;
      const wh = wrap.clientHeight - 16;
      const ratio = CW / CH;
      let w = ww, h = ww / ratio;
      if (h > wh) { h = wh; w = h * ratio; }
      canvas.style.width  = w + 'px';
      canvas.style.height = h + 'px';
    };
    const ro = new ResizeObserver(fit);
    ro.observe(wrap);
    fit();
    return () => ro.disconnect();
  }, [loading]);

  const draw = useCallback((idx) => {
    const canvas = canvasRef.current;
    const f = framesRef.current;
    const m = metaRef.current;
    if (!canvas || !f.length || !m) return;

    const { CW, CH, FY0, FY1 } = m.canvas;
    const FH = FY1 - FY0;
    const ctx = canvas.getContext('2d');
    const r = f[idx];

    ctx.clearRect(0, 0, CW, CH);
    ctx.fillStyle = '#0a0a0a';
    ctx.fillRect(0, 0, CW, CH);

    STRIPES.forEach(([f0, f1, c1, c2]) => {
      const y0 = FY0 + f0 * FH, y1 = FY0 + f1 * FH;
      const grad = ctx.createLinearGradient(0, y0, 0, y1);
      grad.addColorStop(0, c1); grad.addColorStop(0.5, c2); grad.addColorStop(1, c1);
      ctx.fillStyle = grad;
      ctx.fillRect(0, y0, CW, y1 - y0);
    });

    ctx.strokeStyle = 'rgba(255,255,255,0.22)';
    ctx.lineWidth = 1;
    ctx.setLineDash([6, 4]);
    for (let i = 1; i < 7; i++) {
      const y = FY0 + (i / 7) * FH;
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(CW, y); ctx.stroke();
    }
    ctx.setLineDash([]);

    ctx.strokeStyle = 'white';
    ctx.lineWidth = 2.5;
    ctx.strokeRect(12, FY0, CW - 24, FH);

    ctx.strokeStyle = 'white';
    ctx.lineWidth = 2;
    const midY = FY0 + FH / 2;
    ctx.beginPath(); ctx.moveTo(12, midY); ctx.lineTo(CW - 12, midY); ctx.stroke();
    ctx.beginPath(); ctx.arc(CW / 2, midY, 44, 0, Math.PI * 2); ctx.stroke();
    ctx.beginPath(); ctx.arc(CW / 2, midY, 3, 0, Math.PI * 2);
    ctx.fillStyle = 'white'; ctx.fill();

    ctx.strokeStyle = 'white';
    ctx.lineWidth = 2;
    const gw = CW * (18 / 68), gx = (CW - gw) / 2;
    ctx.strokeRect(gx, FY0,              gw, FH * 0.05);
    ctx.strokeRect(gx, FY1 - FH * 0.05, gw, FH * 0.05);

    const { goalTop, goalBot } = m;
    if (goalTop && goalBot) {
      const gtW = goalTop.x2 - goalTop.x1;
      ctx.fillStyle = 'rgba(21,101,192,0.45)';
      ctx.fillRect(goalTop.x1, goalTop.y1, gtW, goalTop.y2 - goalTop.y1);
      ctx.strokeStyle = '#42a5f5'; ctx.lineWidth = 2.5;
      ctx.strokeRect(goalTop.x1, goalTop.y1, gtW, goalTop.y2 - goalTop.y1);
      ctx.fillStyle = 'rgba(66,165,245,0.9)';
      ctx.font = 'bold 11px sans-serif'; ctx.textAlign = 'center';
      ctx.fillText('BUT BLEU', CW / 2, goalTop.y1 + (goalTop.y2 - goalTop.y1) / 2 + 4);

      const gbW = goalBot.x2 - goalBot.x1;
      ctx.fillStyle = 'rgba(229,9,20,0.45)';
      ctx.fillRect(goalBot.x1, goalBot.y1, gbW, goalBot.y2 - goalBot.y1);
      ctx.strokeStyle = '#ef5350'; ctx.lineWidth = 2.5;
      ctx.strokeRect(goalBot.x1, goalBot.y1, gbW, goalBot.y2 - goalBot.y1);
      ctx.fillStyle = 'rgba(239,83,80,0.9)';
      ctx.fillText('BUT ROUGE', CW / 2, goalBot.y1 + (goalBot.y2 - goalBot.y1) / 2 + 4);
    }

    m.contacts.forEach(c => {
      if (c.t > r.ts) return;
      const fade = Math.max(0, 1 - (r.ts - c.t) / 4000);
      if (fade <= 0) return;
      ctx.globalAlpha = fade * 0.9;
      ctx.beginPath();
      ctx.arc(c.x, c.y, 5 + Math.min(c.deviation / 100, 1) * 8, 0, Math.PI * 2);
      ctx.fillStyle   = c.team === 'blue' ? 'rgba(66,165,245,0.85)'  : 'rgba(239,83,80,0.85)';
      ctx.strokeStyle = c.team === 'blue' ? '#42a5f5' : '#ef5350';
      ctx.fill(); ctx.lineWidth = 1.5; ctx.stroke();
    });
    ctx.globalAlpha = 1;

    const N = 10;
    for (let i = Math.max(0, idx - N); i < idx; i++) {
      const d = f[i]; if (d.kx === null) continue;
      ctx.globalAlpha = ((i - Math.max(0, idx - N)) / N) * 0.45;
      ctx.beginPath(); ctx.arc(d.kx, d.ky, 5, 0, Math.PI * 2);
      ctx.fillStyle = 'white'; ctx.fill();
    }
    ctx.globalAlpha = 1;

    if (r.kx !== null) {
      ctx.shadowColor = 'rgba(0,0,0,0.5)'; ctx.shadowBlur = 10;
      ctx.beginPath(); ctx.arc(r.kx, r.ky, 11, 0, Math.PI * 2);
      ctx.fillStyle = 'white'; ctx.fill();
      ctx.strokeStyle = '#222'; ctx.lineWidth = 1.5; ctx.stroke();
      ctx.shadowBlur = 0;
    }
  }, []);

  useEffect(() => {
    if (!loading && frames.length && meta) draw(current);
  }, [current, loading, frames, meta, draw]);

  useEffect(() => {
    if (playing) {
      playRef.current = setInterval(() => {
        setCurrent(prev => {
          if (prev >= framesRef.current.length - 1) { setPlaying(false); return prev; }
          return prev + 1;
        });
      }, 80);
    } else {
      clearInterval(playRef.current);
    }
    return () => clearInterval(playRef.current);
  }, [playing]);

  useEffect(() => {
    const h = e => {
      if (e.key === 'ArrowRight') setCurrent(p => Math.min(p + 1, framesRef.current.length - 1));
      else if (e.key === 'ArrowLeft')  setCurrent(p => Math.max(p - 1, 0));
      else if (e.key === ' ') { e.preventDefault(); setPlaying(p => !p); }
    };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, []);

  const goTo = idx => setCurrent(Math.max(0, Math.min(frames.length - 1, idx)));

  const seekToTs = ts => {
    let best = 0, bestDist = Infinity;
    frames.forEach((d, i) => { const dist = Math.abs(d.ts - ts); if (dist < bestDist) { bestDist = dist; best = i; } });
    goTo(best);
  };

  const seekToContact = i => {
    if (meta?.contacts[i]) seekToTs(meta.contacts[i].t);
  };

  if (loading) return (
    <div style={{ background: '#111', height: '100vh', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', fontFamily: 'sans-serif', gap: 24 }}>
      <div style={{ fontSize: 22, fontWeight: 900, color: 'white', letterSpacing: '-0.5px' }}>KickAnalytics</div>
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 12, width: 320 }}>
        <div style={{ fontSize: 13, color: '#888', fontWeight: 600 }}>Chargement des données pipeline…</div>
        <div style={{ width: '100%', height: 6, background: '#2a2a3f', borderRadius: 99, overflow: 'hidden' }}>
          <div style={{
            height: '100%', borderRadius: 99, background: '#e50914',
            width: `${progress}%`,
            transition: progress === 0 ? 'none' : 'width 0.15s ease',
          }} />
        </div>
        <div style={{ fontSize: 12, color: '#555', fontWeight: 700 }}>{progress}%</div>
      </div>
    </div>
  );

  if (loadError) return (
    <div style={{ background: '#111', color: '#ef5350', height: '100vh', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', fontFamily: 'sans-serif', gap: 12 }}>
      <div style={{ fontSize: 18, fontWeight: 700 }}>Erreur : {loadError}</div>
      <div style={{ color: '#888', fontSize: 13 }}>Exécutez <code style={{ background: '#1b1b2f', padding: '2px 8px', borderRadius: 4 }}>python test_pipeline.py</code> pour générer les données.</div>
    </div>
  );

  const r = frames[current];
  const pct = Math.round(r.conf * 100);
  const confColor = pct > 60 ? '#4caf50' : pct > 35 ? '#ffc107' : '#e50914';
  const { canvas: cv, matchStats, possession, goalRods, contacts } = meta;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', fontFamily: 'sans-serif', background: '#111', color: '#f0f0f0', overflow: 'hidden' }}>
      <header style={{ height: 50, background: '#e50914', padding: '0 20px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexShrink: 0 }}>
        <div style={{ fontSize: 17, fontWeight: 900, color: 'white' }}>🔬 Pipeline Debug KickAnalytics</div>
        <div style={{ background: 'rgba(255,255,255,0.2)', borderRadius: 8, padding: '5px 16px', fontSize: 16, fontWeight: 900, color: 'white' }}>
          🔴 {r.score_red} – {r.score_blue} 🔵
        </div>
      </header>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 320px 240px', gap: 10, padding: 10, height: 'calc(100vh - 50px)', minHeight: 0 }}>

        <div style={s.panel}>
          <div style={s.panelTitle}>Frame vidéo {current + 1} / {frames.length} (vidéo frame {r.frame_idx})</div>
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'hidden', background: '#000', position: 'relative', minHeight: 0 }}>
            <img src={`data:image/jpeg;base64,${r.frame_b64}`} alt="frame"
              style={{ maxWidth: '100%', maxHeight: '100%', objectFit: 'contain', display: 'block' }} />
            <div style={{ position: 'absolute', top: 8, left: 8, background: 'rgba(0,0,0,0.75)', borderRadius: 6, padding: '3px 10px', fontSize: 12, fontWeight: 700, color: 'white' }}>
              #{r.frame_idx}
            </div>
            {r.scored && (
              <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 52, fontWeight: 900, background: 'rgba(229,9,20,0.35)', pointerEvents: 'none' }}>
                {r.scored === 'red' ? '🔴 BUT !' : '🔵 BUT !'}
              </div>
            )}
          </div>
          <div style={s.navBar}>
            <button style={s.btn} onClick={() => goTo(current - 1)} disabled={current === 0}>◀</button>
            <input type="range" min={0} max={frames.length - 1} value={current}
              onChange={e => goTo(+e.target.value)} style={{ flex: 1, accentColor: '#e50914' }} />
            <button style={s.btn} onClick={() => goTo(current + 1)} disabled={current === frames.length - 1}>▶</button>
          </div>
          <div style={{ ...s.navBar, borderTop: 'none', paddingTop: 0 }}>
            <button style={{ ...s.btn, flex: 1 }} onClick={() => setPlaying(p => !p)}>
              {playing ? '⏸ Pause' : '▶ Play'}
            </button>
            <div style={{ flex: 1, textAlign: 'center', fontSize: 12, fontWeight: 700, color: '#888' }}>{current + 1} / {frames.length}</div>
            <button style={{ ...s.btn, background: '#e50914', borderColor: '#e50914', color: 'white' }} onClick={() => goTo(0)}>⏮</button>
          </div>
        </div>

        <div style={s.panel}>
          <div style={s.panelTitle}>Terrain canvas {cv.CW}×{cv.CH}px (terrain {cv.CW}×{cv.FIELD_H_PX} + buts {cv.GOAL_DEPTH_PX}px)</div>
          <div ref={wrapRef} style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'hidden', padding: 8, minHeight: 0 }}>
            <canvas ref={canvasRef} width={cv.CW} height={cv.CH} style={{ borderRadius: 4 }} />
          </div>
        </div>

        <div style={s.panel}>
          <div style={s.panelTitle}>Pipeline</div>
          <div style={{ flex: 1, overflowY: 'auto', padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 6, minHeight: 0 }}>
            <StatRow label="Frame vidéo" value={r.frame_idx} />
            <StatRow label="Détection" value={
              r.detected
                ? <Pill color="green">Oui</Pill>
                : <Pill color="grey">Non</Pill>
            } />
            <div style={{ ...s.statRow, flexDirection: 'column', alignItems: 'stretch', gap: 3 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={s.statLabel}>Confiance</span>
                <span style={s.statVal}>{pct}%</span>
              </div>
              <div style={{ height: 4, background: '#2a2a3f', borderRadius: 2, overflow: 'hidden' }}>
                <div style={{ height: '100%', width: `${pct}%`, background: confColor, borderRadius: 2, transition: 'width 0.2s' }} />
              </div>
            </div>
            <StatRow label="Pos frame"   value={r.cx_frame  !== null ? `(${r.cx_frame|0},${r.cy_frame|0})`   : '—'} />
            <StatRow label="→ canvas raw" value={r.cx_canvas !== null ? `(${r.cx_canvas|0},${r.cy_canvas|0})` : '—'} />
            <StatRow label="→ Kalman"    value={r.kx         !== null ? `(${r.kx|0},${r.ky|0})`               : '—'} yellow />
            <StatRow label="But frame" value={r.scored
              ? <Pill color={r.scored === 'red' ? 'red' : 'green'}>BUT {r.scored.toUpperCase()}</Pill>
              : <span style={{ color: '#888' }}>—</span>}
            />
            <StatRow label="Score" value={`${r.score_red} – ${r.score_blue}`} />

            <SectionLabel>Historique buts</SectionLabel>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 130, overflowY: 'auto' }}>
              {goalRods.length === 0
                ? <div style={{ fontSize: 11, color: '#888' }}>Aucun but</div>
                : goalRods.map((g, i) => (
                  <div key={i} onClick={() => seekToTs(g.ts)} style={goalEntry(g.team)}>
                    {g.team === 'red' ? '🔴' : '🔵'} {ROD_LABELS[g.rod] || g.rod || g.team} (frame {g.frame_idx})
                  </div>
                ))}
            </div>

            <SectionLabel>Stats attribuées (1v1)</SectionLabel>
            <StatRow2 label="Possession"  blue={`${possession.blue}%`}               red={`${possession.red}%`} />
            <StatRow2 label="Buts"        blue={matchStats.blue?.goals ?? '—'}        red={matchStats.red?.goals ?? '—'} />
            <StatRow2 label="Tirs"        blue={matchStats.blue?.shots_total ?? '—'}  red={matchStats.red?.shots_total ?? '—'} />
            <StatRow2 label="Tirs cadrés" blue={matchStats.blue?.shots_on_target ?? '—'} red={matchStats.red?.shots_on_target ?? '—'} />
            <StatRow2 label="Arrêts"      blue={matchStats.blue?.saves ?? '—'}        red={matchStats.red?.saves ?? '—'} />

            <SectionLabel>Contacts ({contacts.length} détectés)</SectionLabel>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 160, overflowY: 'auto' }}>
              {contacts.length === 0
                ? <div style={{ fontSize: 11, color: '#888' }}>Aucun contact</div>
                : contacts.map((c, i) => (
                  <div key={i} onClick={() => seekToContact(i)} style={{ ...goalEntry(c.team), fontSize: 10 }}>
                    {c.team === 'blue' ? '🔵' : '🔴'} {c.name} — dev {c.deviation}px ({(c.t / 1000).toFixed(1)}s)
                  </div>
                ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function StatRow({ label, value, yellow }) {
  return (
    <div style={s.statRow}>
      <span style={s.statLabel}>{label}</span>
      <span style={{ ...s.statVal, color: yellow ? '#ffc107' : undefined }}>{value}</span>
    </div>
  );
}

function StatRow2({ label, blue, red }) {
  return (
    <div style={s.statRow}>
      <span style={s.statLabel}>{label}</span>
      <span style={{ ...s.statVal, color: '#42a5f5' }}>{blue}</span>
      <span style={{ color: '#888', margin: '0 4px', fontWeight: 900 }}>/</span>
      <span style={{ ...s.statVal, color: '#ef5350' }}>{red}</span>
    </div>
  );
}

function Pill({ color, children }) {
  const colors = {
    green: { background: 'rgba(76,175,80,0.25)',   color: '#81c784' },
    red:   { background: 'rgba(229,9,20,0.25)',    color: '#ef9a9a' },
    grey:  { background: 'rgba(255,255,255,0.08)', color: '#888'    },
  };
  return <span style={{ borderRadius: 5, padding: '2px 8px', fontSize: 10, fontWeight: 800, ...colors[color] }}>{children}</span>;
}

function SectionLabel({ children }) {
  return <div style={{ fontSize: 9, fontWeight: 700, color: '#888', textTransform: 'uppercase', letterSpacing: '1px', padding: '4px 0 2px' }}>{children}</div>;
}

const goalEntry = team => ({
  fontSize: 11, fontWeight: 700, padding: '4px 10px', borderRadius: 6, cursor: 'pointer',
  background: team === 'red' ? 'rgba(229,9,20,0.25)'   : 'rgba(21,101,192,0.25)',
  color:      team === 'red' ? '#ef9a9a'                : '#90caf9',
});

const s = {
  panel:     { background: '#1b1b2f', borderRadius: 10, border: '1px solid #2a2a3f', display: 'flex', flexDirection: 'column', overflow: 'hidden', minHeight: 0 },
  panelTitle:{ fontSize: 10, fontWeight: 700, color: '#888', textTransform: 'uppercase', letterSpacing: '1.5px', padding: '8px 14px 6px', borderBottom: '1px solid #2a2a3f', flexShrink: 0 },
  navBar:    { display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px', borderTop: '1px solid #2a2a3f', flexShrink: 0 },
  btn:       { background: '#1b1b2f', border: '1.5px solid #2a2a3f', color: '#f0f0f0', borderRadius: 8, padding: '7px 14px', fontSize: 12, fontWeight: 800, cursor: 'pointer', fontFamily: 'sans-serif', whiteSpace: 'nowrap' },
  statRow:   { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '6px 10px', background: 'rgba(255,255,255,0.04)', borderRadius: 7, fontSize: 11 },
  statLabel: { color: '#888', fontWeight: 700 },
  statVal:   { fontWeight: 900 },
};
