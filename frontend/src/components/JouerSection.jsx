const TABLE_LABELS = {
  free:           ['🟢 Libre',          'Clique pour jouer'],
  matchmaking:    ['🟡 Salle ouverte',  'En cours de matchmaking'],
  waiting_camera: ['🟠 Cherche caméra', "En attente d'une caméra"],
  calibrating:    ['🔵 Calibration',    'Calibration du terrain en cours'],
  playing:        ['🔴 Match en cours', 'Match en cours'],
  paused:         ['⏸ Pause',           'Caméra déconnectée, en pause'],
};
const COLORS = ['#083879', '#1565c0', '#2e7d32', '#f57f17'];

export default function JouerSection({
  currentUser, myRole, mmMode, tableData,
  showFilmingPanel, showMmPanel, showRolePanel, showCameraPoolPanel,
  mmPanelData, cameraPool, btnMmDisabled,
  onSetMmMode, onStartFilming, onStopFilming, onStartMatchmaking,
  onMmReady, onMmLeave, onOpenController, onSelectCamera, onKickCamera,
}) {
  const mmPlayers = mmPanelData?.players ?? [];
  const mmNeeded  = mmPanelData?.needed  ?? 0;
  const myInfo    = mmPlayers.find(p => p.username === currentUser?.username);

  return (
    <div className="section active">
      <div className="page-content" style={{ maxWidth: '520px' }}>

        {!showFilmingPanel && !showRolePanel && (
          <>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px', marginBottom: '14px' }}>
              <button className="btn-red" style={{ fontSize: '15px', padding: '16px 0' }} onClick={() => onStartFilming(false)}>📷 Je filme</button>
              <button className="btn-red" style={{ fontSize: '15px', padding: '16px 0' }} disabled={btnMmDisabled} onClick={onStartMatchmaking}>
                {btnMmDisabled ? 'Recherche...' : '🎮 Jouer'}
              </button>
            </div>
            <div style={{ display: 'flex', justifyContent: 'center', gap: '12px', marginBottom: '14px' }}>
              <button className={`mode-btn${mmMode === '1v1' ? ' active' : ''}`} onClick={() => onSetMmMode('1v1')}>1v1</button>
              <button className={`mode-btn${mmMode === '2v2' ? ' active' : ''}`} onClick={() => onSetMmMode('2v2')}>2v2</button>
            </div>
          </>
        )}

        {tableData && (() => {
          const [pillLabel, subLabel] = TABLE_LABELS[tableData.state] || ['—', '—'];
          return (
            <div className={`table-card${tableData.state !== 'free' ? ' occupied' : ''}`}>
              <div className="table-card-top">
                <div className="table-icon">⚽</div>
                <div>
                  <div className="table-title">Babyfoot</div>
                  <div className="table-subtitle">{subLabel}</div>
                </div>
                <div className={`table-status-pill ${tableData.state}`}>{pillLabel}</div>
              </div>
              {tableData.state === 'playing' && (
                <div className="table-score-row">
                  <span className="table-score-num">{tableData.score?.red ?? 0}</span>
                  <span className="table-score-sep">-</span>
                  <span className="table-score-num">{tableData.score?.blue ?? 0}</span>
                </div>
              )}
            </div>
          );
        })()}

        {showFilmingPanel && (
          <div className="mm-panel">
            <div className="mm-header">
              <span>📷 Tu filmes, en attente de validation</span>
              <button className="mm-leave" onClick={onStopFilming}>Annuler</button>
            </div>
            <div className="mm-hint">Un controller doit te sélectionner comme caméra</div>
          </div>
        )}

        {showCameraPoolPanel && myRole === 'controller' && tableData?.state === 'waiting_camera' && (
          <div className="mm-panel">
            <div className="mm-header"><span>📷 Caméras disponibles</span></div>
            <div>
              {cameraPool.length === 0 && <div className="mm-slot">Aucune caméra disponible…</div>}
              {cameraPool.map(cam => (
                <div key={cam.username} className="mm-player-row">
                  <div className="mm-avatar" style={{ background: '#083879' }}>📷</div>
                  <span className="mm-player-name">{cam.display_name}</span>
                  <span className="mm-player-elo">@{cam.username}</span>
                  <button className="btn-red" style={{ width: 'auto', padding: '6px 14px', fontSize: '12px' }} onClick={() => onSelectCamera(cam.username)}>Valider</button>
                  <button onClick={() => onKickCamera(cam.username)} style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: '16px', padding: '4px 6px', color: '#999', lineHeight: 1 }}>✕</button>
                </div>
              ))}
              <div className="mm-player-row" style={{ borderTop: '1px solid var(--border)', marginTop: '6px' }}>
                <span className="mm-player-name" style={{ color: 'var(--muted)', fontSize: '13px' }}>Je filme et je joue</span>
                <button className="btn-red" style={{ width: 'auto', padding: '6px 14px', fontSize: '12px', marginLeft: 'auto' }} onClick={() => onStartFilming(true)}>📷 Je filme</button>
              </div>
            </div>
            <div className="mm-hint">Sélectionne une caméra pour démarrer la calibration</div>
          </div>
        )}

        {showMmPanel && mmPanelData && (
          <div className="mm-panel">
            <div className="mm-header">
              <span>{mmPanelData.mode === '1v1' ? 'Salle 1v1' : 'Salle 2v2'} ({mmPlayers.length}/{mmNeeded})</span>
              <button className="mm-leave" onClick={onMmLeave}>Quitter</button>
            </div>
            <div className="mm-players">
              {mmPlayers.map((p, i) => (
                <div key={p.username} className="mm-player-row">
                  <div className="mm-avatar" style={{ background: COLORS[i % 4] }}>{p.display_name[0].toUpperCase()}</div>
                  <span className="mm-player-name">{p.display_name}</span>
                  <span className="mm-player-elo">ELO {p.elo}</span>
                  {p.ready ? <span className="mm-ready-chip">Prêt</span> : <span className="mm-waiting-chip">En attente</span>}
                </div>
              ))}
              {Array.from({ length: Math.max(0, mmNeeded - mmPlayers.length) }).map((_, i) => (
                <div key={i} className="mm-slot">En attente d'un joueur...</div>
              ))}
            </div>
            <div className="mm-hint">
              {mmPlayers.length < mmNeeded
                ? `Attends que ${mmNeeded - mmPlayers.length} joueur(s) rejoignent…`
                : myInfo?.ready ? `En attente de ${mmPlayers.filter(p => !p.ready).length} joueur(s)…`
                : 'Tout le monde est là. Confirme !'}
            </div>
            {mmPlayers.length === mmNeeded && !myInfo?.ready && (
              <button className="btn-red" onClick={onMmReady}>Je suis prêt</button>
            )}
          </div>
        )}

        {showRolePanel && (
          <div className="role-panel">
            <div className="role-panel-icon">🎛</div>
            <div className="role-panel-title">Tu contrôles</div>
            <div className="role-panel-sub">Ouvre le contrôleur pour gérer le match</div>
            <button className="btn-red" onClick={onOpenController}>Ouvrir le contrôleur</button>
          </div>
        )}

      </div>
    </div>
  );
}
