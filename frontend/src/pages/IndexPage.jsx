import { useState, useRef, useEffect, useCallback } from 'react';
import { getWsBase } from '../utils/wsBase';
import '../styles/home.css';
import LiveSection    from '../components/LiveSection';
import JouerSection   from '../components/JouerSection';
import ProfileDrawer  from '../components/ProfileDrawer';

export default function IndexPage() {
  const [activeSection, setActiveSection] = useState('home');

  const [currentUser, setCurrentUser] = useState(null);
  const currentUserRef = useRef(null);

  const [showProfile, setShowProfile]   = useState(false);
  const [profileStats, setProfileStats] = useState(null);

  const [scoreRed, setScoreRed]     = useState(0);
  const [scoreBlue, setScoreBlue]   = useState(0);
  const [liveStatus, setLiveStatus] = useState({ text: 'Déconnecté', type: '' });
  const [latency, setLatency]       = useState('—');
  const [ballPos, setBallPos]       = useState(null);
  const [showPauseOverlay, setShowPauseOverlay] = useState(false);
  const [goalFlash, setGoalFlash]   = useState(null);
  const [replayFrames, setReplayFrames] = useState(null);
  const [goals, setGoals] = useState([]);
  const matchStartRef = useRef(null);
  const wsRef = useRef(null);

  const [leaderboard, setLeaderboard] = useState(null);

  const [mmMode, setMmMode]           = useState('1v1');
  const [tableData, setTableData]     = useState(null);
  const [myRole, setMyRole]           = useState(null);
  const [showFilmingPanel, setShowFilmingPanel]       = useState(false);
  const [showMmPanel, setShowMmPanel]                 = useState(false);
  const [showRolePanel, setShowRolePanel]             = useState(false);
  const [showCameraPoolPanel, setShowCameraPoolPanel] = useState(false);
  const [mmPanelData, setMmPanelData] = useState(null);
  const [btnMmDisabled, setBtnMmDisabled] = useState(false);
  const myRoleRef    = useRef(null);
  const isFilmingRef = useRef(false);
  const lobbyWsRef   = useRef(null);
  const pendingCbsRef     = useRef([]);
  const lastTableDataRef  = useRef(null);
  const lastTableStateRef = useRef(null);

  useEffect(() => {
    const saved = localStorage.getItem('ka_user');
    if (saved) { try { const u = JSON.parse(saved); setCurrentUser(u); currentUserRef.current = u; } catch {} }
  }, []);

  useEffect(() => {
    window.dumpSets = async () => {
      try {
        const res = await fetch('/api/debug/dump-sets', { method: 'POST' });
        const data = await res.json();
        if (!res.ok) { console.error('[dumpSets] error', data); return data; }
        console.log('[dumpSets] state snapshot', data); return data;
      } catch (err) { console.error('[dumpSets] network error', err); return null; }
    };
  }, []);

  const renderTableStatus = useCallback((d) => {
    lastTableDataRef.current  = d;
    lastTableStateRef.current = d.state;
    setTableData(d);
    if (d.room?.players.some(p => p.username === currentUserRef.current?.username)) {
      setMmPanelData(d.room);
      setShowMmPanel(true);
    }
    if (myRoleRef.current === 'controller' && d.state === 'waiting_camera') setShowCameraPoolPanel(true);
  }, []);

  const connectSpectator = useCallback(() => {
    if (wsRef.current) return;
    let opened = false;
    wsRef.current = new WebSocket(`${getWsBase()}/spectator`);
    wsRef.current.onopen  = () => { opened = true; setLiveStatus({ text: 'Connecté', type: 'ok' }); };
    wsRef.current.onclose = () => {
      wsRef.current = null;
      setLiveStatus(opened ? { text: 'Déconnecté', type: '' } : { text: 'Connexion refusée (auth requise)', type: 'err' });
    };
    wsRef.current.onmessage = (e) => {
      const d = JSON.parse(e.data);
      if (d.type === 'table_status')       { renderTableStatus(d); return; }
      if (d.type === 'camera_ready')       setLiveStatus({ text: '📱 Caméra prête', type: '' });
      if (d.type === 'match_paused')       { setLiveStatus({ text: '⏸ Match en pause', type: 'err' }); setShowPauseOverlay(true); }
      if (d.type === 'camera_resumed')     { setLiveStatus({ text: '▶ Match repris', type: 'ok' }); setShowPauseOverlay(false); }
      if (d.type === 'calibration_ok')     { setLiveStatus({ text: '🟢 Match en cours', type: 'ok' }); setScoreRed(0); setScoreBlue(0); setGoals([]); matchStartRef.current = Date.now(); }
      if (d.type === 'calibration_failed') setLiveStatus({ text: '❌ Calibration échouée', type: 'err' });
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
      if (d.type === 'match_end') setLiveStatus({ text: '🏁 Match terminé', type: '' });
      if (d.type === 'replay')    setReplayFrames(d.frames);
    };
  }, [renderTableStatus]);

  const disconnectSpectator = useCallback(() => { wsRef.current?.close(); wsRef.current = null; }, []);

  useEffect(() => {
    if (activeSection === 'live' || activeSection === 'home') connectSpectator();
    else disconnectSpectator();
  }, [activeSection, connectSpectator, disconnectSpectator]);

  const loadLeaderboard = useCallback(async () => {
    setLeaderboard(undefined);
    try {
      const res = await fetch('/api/leaderboard');
      if (!res.ok) throw new Error();
      setLeaderboard(await res.json());
    } catch { setLeaderboard(false); }
  }, []);

  useEffect(() => { if (activeSection === 'stats') loadLeaderboard(); }, [activeSection, loadLeaderboard]);

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
    setCurrentUser(null); currentUserRef.current = null;
    localStorage.removeItem('ka_user');
    lobbyClose();
    setShowMmPanel(false); setShowRolePanel(false);
    setShowFilmingPanel(false); setShowCameraPoolPanel(false);
    setBtnMmDisabled(false);
    setMyRole(null); myRoleRef.current = null;
    isFilmingRef.current = false;
    window.location.href = '/auth';
  }, []);

  function lobbyClose() {
    lobbyWsRef.current?.close(); lobbyWsRef.current = null; pendingCbsRef.current = [];
  }

  const ensureLobbyConnected = useCallback((onOpen) => {
    if (lobbyWsRef.current?.readyState === WebSocket.OPEN) { onOpen(); return; }
    if (lobbyWsRef.current?.readyState === WebSocket.CONNECTING) { pendingCbsRef.current.push(onOpen); return; }
    pendingCbsRef.current.push(onOpen);
    let opened = false;
    lobbyWsRef.current = new WebSocket(`${getWsBase()}/lobby`);
    lobbyWsRef.current.onopen = () => {
      opened = true;
      const cbs = pendingCbsRef.current; pendingCbsRef.current = [];
      cbs.forEach(cb => cb());
    };
    lobbyWsRef.current.onclose = () => {
      if (!opened) {
        alert('Session expirée ou non authentifiée. Reconnecte-toi pour jouer.');
        setBtnMmDisabled(false); setShowFilmingPanel(false); setShowMmPanel(false);
      }
      lobbyWsRef.current = null; pendingCbsRef.current = [];
    };
    lobbyWsRef.current.onmessage = (e) => {
      let d; try { d = JSON.parse(e.data); } catch { return; }
      if (d.type === 'table_status') { renderTableStatus(d); if (d.state === 'free' || d.state === 'matchmaking') setBtnMmDisabled(false); }
      if (d.type === 'mm_error')  alert(d.error);
      if (d.type === 'mm_start')  {
        setMyRole('controller'); myRoleRef.current = 'controller';
        setShowMmPanel(false); setShowRolePanel(true);
        if (lastTableStateRef.current === 'waiting_camera') setShowCameraPoolPanel(true);
      }
      if (d.type === 'match_paused')   { setShowPauseOverlay(true);  setShowCameraPoolPanel(true); }
      if (d.type === 'camera_resumed') { setShowPauseOverlay(false); setShowCameraPoolPanel(false); }
      if (d.type === 'camera_validated' && isFilmingRef.current && myRoleRef.current === 'camera') {
        document.cookie = 'ka_page_access=camera; Path=/; SameSite=Lax';
        window.location.href = '/camera';
      }
      if (d.type === 'elo_update' && d.new_elos && currentUserRef.current) {
        const newElo = d.new_elos[currentUserRef.current.username];
        if (newElo !== undefined && newElo !== currentUserRef.current.elo) {
          const updated = { ...currentUserRef.current, elo: newElo };
          setCurrentUser(updated); currentUserRef.current = updated;
          localStorage.setItem('ka_user', JSON.stringify(updated));
        }
      }
    };
  }, [renderTableStatus]);

  const startFilming = useCallback((asPlayer = false) => {
    if (asPlayer) { document.cookie = 'ka_page_access=camera; Path=/; SameSite=Lax'; window.location.href = '/camera'; return; }
    isFilmingRef.current = true; setMyRole('camera'); myRoleRef.current = 'camera';
    setShowFilmingPanel(true);
    ensureLobbyConnected(() => {
      // this callback will be called once the lobby ws opens
      if (!isFilmingRef.current || myRoleRef.current !== 'camera') return;
      const u = currentUserRef.current || {};
      lobbyWsRef.current?.send(JSON.stringify({ type: 'lobby_film', username: u.username || 'inconnu', display_name: u.display_name || 'Inconnu' }));
    });
  }, [ensureLobbyConnected]);

  const stopFilming = useCallback(() => {
    lobbyWsRef.current?.send(JSON.stringify({ type: 'lobby_stop_film' }));
    isFilmingRef.current = false; setMyRole(null); myRoleRef.current = null;
    setShowFilmingPanel(false); lobbyClose();
  }, []);

  const startMatchmaking = useCallback(() => {
    setBtnMmDisabled(true);
    const u = currentUserRef.current;
    ensureLobbyConnected(() => {
      lobbyWsRef.current?.send(JSON.stringify({ type: 'mm_join', username: u.username, display_name: u.display_name, elo: u.elo, mode: mmMode }));
    });
  }, [ensureLobbyConnected, mmMode]);

  const mmLeave = useCallback(() => {
    lobbyWsRef.current?.send(JSON.stringify({ type: 'mm_leave' }));
    setMyRole(null); myRoleRef.current = null;
    setShowMmPanel(false); setShowRolePanel(false); setShowCameraPoolPanel(false);
    setBtnMmDisabled(false); lobbyClose();
  }, []);

  const openController = useCallback(() => {
    lobbyWsRef.current?.send(JSON.stringify({ type: 'mm_become_controller' }));
    document.cookie = 'ka_page_access=controller; Path=/; SameSite=Lax';
    window.location.href = '/controller';
  }, []);

  const switchSection = useCallback((id) => {
    if (id !== 'jouer' && myRoleRef.current === 'controller' && lobbyWsRef.current?.readyState === WebSocket.OPEN) {
      lobbyWsRef.current.send(JSON.stringify({ type: 'mm_leave_match' }));
      setMyRole(null); myRoleRef.current = null;
      setShowRolePanel(false); setShowCameraPoolPanel(false); setShowMmPanel(false);
      setBtnMmDisabled(false); lobbyClose();
    }
    setActiveSection(id);
    if (id === 'jouer' && lobbyWsRef.current?.readyState === WebSocket.OPEN && lastTableDataRef.current) {
      renderTableStatus(lastTableDataRef.current);
      if (myRoleRef.current === 'controller') {
        setShowRolePanel(true);
        if (['waiting_camera','paused'].includes(lastTableStateRef.current)) setShowCameraPoolPanel(true);
      }
    }
  }, [renderTableStatus]);

  const avatarLetter = currentUser ? (currentUser.display_name || currentUser.username || '?')[0].toUpperCase() : '?';

  const cameraPool = (() => {
    if (!tableData?.camera_pool) return [];
    const seen = new Set();
    return tableData.camera_pool.filter(c => { if (seen.has(c.username)) return false; seen.add(c.username); return true; });
  })();

  const redPlayer  = tableData?.room?.players?.[0];
  const bluePlayer = tableData?.room?.players?.[1];

  return (
    <>
      <header>
        <div className="logo">KickAnalytics</div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <button className="header-avatar" onClick={openProfile} title="Mon compte">{avatarLetter}</button>
          <button onClick={logout} style={{ background: 'rgba(255,255,255,0.15)', border: '1px solid rgba(255,255,255,0.3)', color: 'white', borderRadius: '20px', padding: '5px 12px', fontSize: '12px', fontWeight: 700, cursor: 'pointer', fontFamily: 'sans-serif' }}>
            Déconnexion
          </button>
        </div>
      </header>

      {activeSection === 'home' && (
        <div className="section active">
          <div className="page-content" style={{ paddingTop: '16px' }}>

            {/* Match card */}
            <div className="match-card" style={{ background: '#1a3a8a' }}>
              <div className="match-card-gradient" />
              <div className="match-card-inner">

                {/* Header — just KickAnalytics centered */}
                <h2 className="match-card-title">KickAnalytics</h2>

                {/* Score grid */}
                <div className="match-score-grid">
                  <p className="match-player-name">{redPlayer?.display_name || 'Rouge'}</p>
                  <div className="match-score-center">
                    <span className="match-date">
                      {new Date().toLocaleDateString('fr-FR', { weekday: 'short', day: 'numeric', month: 'short' })}
                    </span>
                    <div className="match-score-row">
                      <span className="match-score-num">{scoreRed}</span>
                      <span className="match-vs">VS</span>
                      <span className="match-score-num">{scoreBlue}</span>
                    </div>
                  </div>
                  <p className="match-player-name">{bluePlayer?.display_name || 'Bleu'}</p>
                </div>

                {/* Goal scorers — two columns separated by ⚽ */}
                {goals.length > 0 && (
                  <div className="match-goals-list">
                    {(() => {
                      const redGoals  = goals.filter(g => g.team === 'red');
                      const blueGoals = goals.filter(g => g.team === 'blue');
                      const rows = Math.max(redGoals.length, blueGoals.length);
                      return Array.from({ length: rows }).map((_, i) => (
                        <div key={i} className="match-goal-row">
                          <span className="match-goal-red">
                            {redGoals[i] ? `${redPlayer?.display_name || 'Rouge'} ${redGoals[i].minute}'` : ''}
                          </span>
                          <span>⚽</span>
                          <span className="match-goal-blue">
                            {blueGoals[i] ? `${blueGoals[i].minute}' ${bluePlayer?.display_name || 'Bleu'}` : ''}
                          </span>
                        </div>
                      ));
                    })()}
                  </div>
                )}

                {/* Watch Now */}
                <button className="match-watch-btn" onClick={() => switchSection('live')}>
                  WATCH NOW
                </button>
              </div>
            </div>

            {/* Table status card */}
            <div className="match-table-card" style={{ background: '#0d1b3e', color: 'white' }}>
              <div className="match-table-title">État de la table</div>
              <div className="match-table-state">
                {{ free: '🟢 Libre', matchmaking: '🟡 Matchmaking en cours', waiting_camera: '🟠 En attente d\'une caméra', calibrating: '🔵 Calibration…', playing: '🔴 Match en cours', paused: '⏸ Pause' }[tableData?.state] || '— Connexion…'}
              </div>
            </div>

          </div>
        </div>
      )}

      {activeSection === 'live' && (
        <LiveSection
          scoreRed={scoreRed} scoreBlue={scoreBlue} liveStatus={liveStatus}
          latency={latency} ballPos={ballPos} showPauseOverlay={showPauseOverlay}
          goalFlash={goalFlash} replayFrames={replayFrames}
        />
      )}

      {activeSection === 'jouer' && (
        <JouerSection
          currentUser={currentUser} myRole={myRole} mmMode={mmMode} tableData={tableData}
          showFilmingPanel={showFilmingPanel} showMmPanel={showMmPanel}
          showRolePanel={showRolePanel} showCameraPoolPanel={showCameraPoolPanel}
          mmPanelData={mmPanelData} cameraPool={cameraPool} btnMmDisabled={btnMmDisabled}
          onSetMmMode={setMmMode} onStartFilming={startFilming} onStopFilming={stopFilming}
          onStartMatchmaking={startMatchmaking} onMmReady={() => lobbyWsRef.current?.send(JSON.stringify({ type: 'mm_ready' }))}
          onMmLeave={mmLeave} onOpenController={openController}
          onSelectCamera={(u) => lobbyWsRef.current?.send(JSON.stringify({ type: 'select_camera', username: u }))}
          onKickCamera={(u) => lobbyWsRef.current?.send(JSON.stringify({ type: 'kick_camera', username: u }))}
        />
      )}

      {activeSection === 'stats' && (
        <div className="section active">
          <div className="page-content">
            <div className="section-header" style={{ marginBottom: '12px' }}>🏆 Classement</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {leaderboard === undefined && <div style={{ textAlign: 'center', color: 'var(--muted)', padding: '24px', fontWeight: 600 }}>Chargement...</div>}
              {leaderboard === false     && <div style={{ textAlign: 'center', color: 'var(--muted)', padding: '24px', fontWeight: 600 }}>Impossible de charger le classement</div>}
              {Array.isArray(leaderboard) && leaderboard.length === 0 && <div style={{ textAlign: 'center', color: 'var(--muted)', padding: '24px', fontWeight: 600 }}>Aucun joueur enregistré</div>}
              {Array.isArray(leaderboard) && leaderboard.map((r, i) => {
                const rankClass = i === 0 ? 'gold' : i === 1 ? 'silver' : i === 2 ? 'bronze' : '';
                const rankEmoji = i === 0 ? '🥇' : i === 1 ? '🥈' : i === 2 ? '🥉' : (i + 1);
                return (
                  <div key={r.username} className="leaderboard-row">
                    <span className={`lb-rank${rankClass ? ' ' + rankClass : ''}`}>{rankEmoji}</span>
                    <div className="lb-name">
                      <div className="lb-display">{r.display_name}</div>
                      <div className="lb-username">@{r.username} · {r.matches_played} match{r.matches_played !== 1 ? 's' : ''}</div>
                    </div>
                    <div className="lb-stats"><span className="lb-stat-line">Win {r.winrate_pct != null ? r.winrate_pct + '%' : '—'} · Précision {r.avg_precision_pct != null ? r.avg_precision_pct + '%' : '—'}</span></div>
                    <span className="lb-elo">{r.elo}</span>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}

      <footer>
        <button className={activeSection === 'home'  ? 'active' : ''} onClick={() => switchSection('home')} ><span className="icon">🏠</span>Home</button>
        <button className={activeSection === 'live'  ? 'active' : ''} onClick={() => switchSection('live')} ><span className="icon">📺</span>Live</button>
        <button className={activeSection === 'jouer' ? 'active' : ''} onClick={() => switchSection('jouer')}><span className="icon">🎮</span>Play</button>
        <button className={activeSection === 'stats' ? 'active' : ''} onClick={() => switchSection('stats')}><span className="icon">🏆</span>Leaderboard</button>
      </footer>

      <ProfileDrawer
        show={showProfile} currentUser={currentUser} stats={profileStats}
        onClose={() => setShowProfile(false)} onLogout={logout}
      />
    </>
  );
}
