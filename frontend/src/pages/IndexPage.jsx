import { useState, useRef, useEffect, useCallback } from 'react';
import { getWsBase } from '../utils/wsBase';
import '../styles/home.css';
import LiveSection   from '../components/LiveSection';
import JouerSection  from '../components/JouerSection';
import ProfileDrawer from '../components/ProfileDrawer';

export default function IndexPage() {
  const [activeSection, setActiveSection] = useState('home');

  const [currentUser, setCurrentUser] = useState(null);
  const [isAdmin, setIsAdmin]         = useState(false);
  const currentUserRef = useRef(null);

  const [showProfile, setShowProfile]   = useState(false);
  const [profileStats, setProfileStats] = useState(null);

  const [scoreRed, setScoreRed]     = useState(0);
  const [scoreBlue, setScoreBlue]   = useState(0);
  const [liveStatus, setLiveStatus] = useState({ text: 'Disconnected', type: '' });
  const [latency, setLatency]       = useState('—');
  const [ballPos, setBallPos]       = useState(null);
  const [showPauseOverlay, setShowPauseOverlay] = useState(false);
  const [goalFlash, setGoalFlash]   = useState(null);
  const [replayFrames, setReplayFrames] = useState(null);
  const [goals, setGoals]           = useState([]);
  const matchStartRef = useRef(null);
  const wsRef = useRef(null);

  const [matchPlayers, setMatchPlayers]   = useState(null);
  const [tableData, setTableData]         = useState(null);
  const [leaderboard, setLeaderboard]     = useState(null);
  const [pendingInvite, setPendingInvite]         = useState(null);
  const [acceptedUsernames, setAcceptedUsernames] = useState(new Set());
  const mountedRef = useRef(true);

  useEffect(() => {
    const saved = localStorage.getItem('ka_user');
    if (saved) {
      try {
        const u = JSON.parse(saved);
        setCurrentUser(u);
        currentUserRef.current = u;
      } catch {}
    }
    fetch('/api/me').then(r => r.ok ? r.json() : null).then(d => {
      if (d?.is_admin) setIsAdmin(true);
    }).catch(() => {});
  }, []);

  const connectSpectator = useCallback(() => {
    if (wsRef.current) return;
    let opened = false;
    wsRef.current = new WebSocket(`${getWsBase()}/spectator`);
    wsRef.current.onopen  = () => { opened = true; setLiveStatus({ text: 'Connected', type: 'ok' }); };
    wsRef.current.onclose = () => {
      wsRef.current = null;
      if (!opened) {
        setLiveStatus({ text: 'Session expired', type: 'err' });
        window.location.href = '/auth';
        return;
      }
      setLiveStatus({ text: 'Disconnected', type: '' });
      if (mountedRef.current) setTimeout(connectSpectator, 3000);
    };
    wsRef.current.onmessage = (e) => {
      const d = JSON.parse(e.data);
      if (d.type === 'table_status')    { setTableData(d); return; }
      if (d.type === 'match_paused')    { setLiveStatus({ text: '⏸ Match paused', type: 'err' }); setShowPauseOverlay(true); }
      if (d.type === 'calibration_ok')  { setLiveStatus({ text: '🟢 Match in progress', type: 'ok' }); setScoreRed(0); setScoreBlue(0); setGoals([]); matchStartRef.current = Date.now(); fetch('/api/live/players').then(r => r.ok ? r.json() : null).then(p => { if (p) setMatchPlayers(p); }).catch(() => {}); }
      if (d.type === 'calibration_failed') setLiveStatus({ text: '❌ Calibration failed', type: 'err' });
      if (d.type === 'position') {
        setBallPos({ x: d.x, y: d.y });
        if (d.ts) setLatency((Date.now() - d.ts) + 'ms');
        if (d.score) { setScoreRed(d.score.red); setScoreBlue(d.score.blue); }
      }
      if (d.type === 'goal' && d.score) {
        setScoreRed(d.score.red); setScoreBlue(d.score.blue);
        setGoalFlash({ team: d.team, rod: d.rod, key: Date.now() });
        const minute = matchStartRef.current ? Math.max(1, Math.round((Date.now() - matchStartRef.current) / 60000)) : '?';
        setGoals(prev => [...prev, { team: d.team, minute }]);
      }
      if (d.type === 'match_end') { setLiveStatus({ text: '🏁 Match over', type: '' }); setTableData(t => ({ ...t, state: 'free' })); setMatchPlayers(null); }
      if (d.type === 'replay')    setReplayFrames(d.frames);
      if (d.type === 'match_invite')    setPendingInvite(d);
      if (d.type === 'player_accepted') setAcceptedUsernames(prev => new Set([...prev, d.username]));
      if (d.type === 'elo_update' && d.new_elos && currentUserRef.current) {
        const newElo = d.new_elos[currentUserRef.current.username];
        if (newElo !== undefined && newElo !== currentUserRef.current.elo) {
          const updated = { ...currentUserRef.current, elo: newElo };
          setCurrentUser(updated); currentUserRef.current = updated;
          localStorage.setItem('ka_user', JSON.stringify(updated));
        }
      }
    };
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    connectSpectator();
    return () => {
      mountedRef.current = false;
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [connectSpectator]);

  const loadLeaderboard = useCallback(async () => {
    setLeaderboard(undefined);
    try {
      const res = await fetch('/api/leaderboard');
      if (!res.ok) throw new Error();
      setLeaderboard(await res.json());
    } catch { setLeaderboard(false); }
  }, []);

  useEffect(() => { if (activeSection === 'stats') loadLeaderboard(); }, [activeSection, loadLeaderboard]);

  useEffect(() => {
    if (activeSection === 'live') {
      document.body.style.overflow = 'hidden';
      fetch('/api/live/players').then(r => r.ok ? r.json() : null).then(p => { if (p) setMatchPlayers(p); }).catch(() => {});
      return () => { document.body.style.overflow = ''; };
    }
  }, [activeSection]);

  const openProfile = useCallback(async () => {
    if (!currentUserRef.current) return;
    setShowProfile(true); setProfileStats(null);
    try {
      const res = await fetch(`/api/players/${currentUserRef.current.username}/stats`);
      setProfileStats(res.ok ? await res.json() : false);
    } catch { setProfileStats(false); }
  }, []);

  const logout = useCallback(() => {
    fetch('/api/auth/logout', { method: 'POST' }).catch(() => {});
    localStorage.removeItem('ka_user');
    window.location.href = '/auth';
  }, []);

  const acceptInvite = useCallback(async () => {
    if (!pendingInvite) return;
    try {
      const res = await fetch(`/api/invites/${pendingInvite.match_id}/accept`, { method: 'POST' });
      if (res.ok) setPendingInvite(null);
    } catch {}
  }, [pendingInvite]);

  const avatarLetter = currentUser ? (currentUser.display_name || currentUser.username || '?')[0].toUpperCase() : '?';

  const handleProfileUpdate = (updated) => {
    setCurrentUser(updated);
    currentUserRef.current = updated;
  };

  return (
    <>
      <header>
        <div className="logo">KickAnalytics</div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <button className="header-avatar" onClick={openProfile} title="Mon compte">
            {currentUser?.avatar
              ? <img src={currentUser.avatar} style={{ width: '100%', height: '100%', borderRadius: '50%', objectFit: 'cover' }} alt="" />
              : avatarLetter}
          </button>
          <button onClick={logout} style={{ background: 'rgba(255,255,255,0.15)', border: '1px solid rgba(255,255,255,0.3)', color: 'white', borderRadius: '20px', padding: '5px 12px', fontSize: '12px', fontWeight: 700, cursor: 'pointer', fontFamily: 'sans-serif' }}>
            Sign out
          </button>
        </div>
      </header>

      {activeSection === 'home' && (
        <div className="section active">
          <div className="page-content" style={{ paddingTop: '16px' }}>

            <div className="match-card" style={{ background: '#1e2f45' }}>
              <div className="match-card-gradient" />
              <div className="match-card-inner">
                <h2 className="match-card-title">KickAnalytics</h2>
                <div className="match-score-row">
                  <span className="match-score-num">{scoreRed}</span>
                  <span className="match-vs">VS</span>
                  <span className="match-score-num">{scoreBlue}</span>
                </div>
                {goals.length > 0 && (
                  <div className="match-goals-list">
                    {(() => {
                      const redGoals  = goals.filter(g => g.team === 'red');
                      const blueGoals = goals.filter(g => g.team === 'blue');
                      const rows = Math.max(redGoals.length, blueGoals.length);
                      return Array.from({ length: rows }).map((_, i) => (
                        <div key={i} className="match-goal-row">
                          <span className="match-goal-red">{redGoals[i]  ? `Red ${redGoals[i].minute}'`  : ''}</span>
                          <span>⚽</span>
                          <span className="match-goal-blue">{blueGoals[i] ? `${blueGoals[i].minute}' Blue` : ''}</span>
                        </div>
                      ));
                    })()}
                  </div>
                )}
                <button className="match-watch-btn" onClick={() => setActiveSection('live')}>WATCH NOW</button>
              </div>
            </div>

            <div className="match-table-card" style={{ background: '#0e1520', color: 'white' }}>
              <div className="match-table-title">Table status</div>
              <div className="match-table-state">
                {{ free: '🟢 Free', calibrating: '🔵 Calibrating…', playing: '🔴 Match in progress' }[tableData?.state] || '— Connecting…'}
              </div>
            </div>

          </div>
        </div>
      )}

      {activeSection === 'live' && (
        <LiveSection
          scoreRed={scoreRed} scoreBlue={scoreBlue} liveStatus={liveStatus}
          latency={latency} ballPos={ballPos} showPauseOverlay={showPauseOverlay}
          goalFlash={goalFlash} replayFrames={replayFrames} goals={goals}
          matchPlayers={matchPlayers}
        />
      )}

      {activeSection === 'jouer' && (
        <JouerSection
          currentUser={currentUser}
          isAdmin={isAdmin}
          tableData={tableData}
          pendingInvite={pendingInvite}
          acceptedUsernames={acceptedUsernames}
          onAcceptInvite={acceptInvite}
          onMatchStarted={() => setAcceptedUsernames(new Set())}
          onReset={() => setAcceptedUsernames(new Set())}
        />
      )}

      {activeSection === 'stats' && (
        <div className="section active">
          <div className="page-content">
            <div className="section-header" style={{ marginBottom: '12px' }}>🏆 Leaderboard</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {leaderboard === undefined && <div style={{ textAlign: 'center', color: 'var(--muted)', padding: '24px', fontWeight: 600 }}>Loading...</div>}
              {leaderboard === false     && <div style={{ textAlign: 'center', color: 'var(--muted)', padding: '24px', fontWeight: 600 }}>Unable to load leaderboard</div>}
              {Array.isArray(leaderboard) && leaderboard.length === 0 && <div style={{ textAlign: 'center', color: 'var(--muted)', padding: '24px', fontWeight: 600 }}>No players registered</div>}
              {Array.isArray(leaderboard) && leaderboard.map((r, i) => {
                const rankEmoji = i === 0 ? '🥇' : i === 1 ? '🥈' : i === 2 ? '🥉' : (i + 1);
                return (
                  <div key={r.username} className="leaderboard-row">
                    <span className={`lb-rank${i < 3 ? ' ' + ['gold','silver','bronze'][i] : ''}`}>{rankEmoji}</span>
                    <div className="lb-name">
                      <div className="lb-display">{r.display_name}</div>
                      <div className="lb-username">@{r.username} · {r.matches_played} match{r.matches_played !== 1 ? 's' : ''}</div>
                    </div>
                    <div className="lb-stats"><span className="lb-stat-line">Win {r.winrate_pct != null ? r.winrate_pct + '%' : '—'} · Accuracy {r.avg_precision_pct != null ? r.avg_precision_pct + '%' : '—'}</span></div>
                    <span className="lb-elo">{r.elo}</span>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}

      <footer>
        <button className={activeSection === 'home'  ? 'active' : ''} onClick={() => setActiveSection('home')} ><span className="icon">🏠</span>Home</button>
        <button className={activeSection === 'live'  ? 'active' : ''} onClick={() => setActiveSection('live')} ><span className="icon">📺</span>Live</button>
        {isAdmin
          ? <button onClick={() => { document.cookie = 'ka_page_access=camera; Path=/; SameSite=Lax'; window.location.href = '/camera'; }}><span className="icon">📷</span>Record</button>
          : <button className={activeSection === 'jouer' ? 'active' : ''} onClick={() => setActiveSection('jouer')}>
              <span className="icon" style={{ position: 'relative', display: 'inline-block' }}>
                🎮
                {pendingInvite && <span style={{ position: 'absolute', top: '-2px', right: '-4px', width: '8px', height: '8px', borderRadius: '50%', background: 'var(--red)', border: '1.5px solid var(--bg)' }} />}
              </span>
              Play
            </button>
        }
        <button className={activeSection === 'stats' ? 'active' : ''} onClick={() => setActiveSection('stats')}><span className="icon">🏆</span>Leaderboard</button>
      </footer>

      <ProfileDrawer
        show={showProfile} currentUser={currentUser} stats={profileStats}
        onClose={() => setShowProfile(false)} onLogout={logout} onUpdate={handleProfileUpdate}
      />
    </>
  );
}
