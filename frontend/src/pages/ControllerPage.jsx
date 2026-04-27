import '../styles/controller.css';
import { useControllerWs } from '../hooks/useControllerWs';

export default function ControllerPage() {
  const ctrl = useControllerWs();

  return (
    <>
      <header className="ctrl-header">
        <div className="logo">KickAnalytics</div>
        <button className="back-link" onClick={ctrl.leaveController}>Retour</button>
      </header>

      <div className="page-content">
        <div className="ctrl-layout">

          {/* Colonne gauche : score + preview */}
          <div>
            <div className="score-card">
              <div className="match-meta">
                <span>Contrôleur</span>
                <span>{ctrl.match.mode || '1v1'}</span>
              </div>

              <div className="score-row">
                <div className="team">
                  <div className="team-badge red">🔴</div>
                  <span className="team-name">Rouge</span>
                  <div className="team-players">
                    {ctrl.match.red.length > 0
                      ? ctrl.match.red.map((p, i) => (
                          <span key={i} className="team-player">{p.display_name || p.username}</span>
                        ))
                      : <span className="team-player">—</span>
                    }
                  </div>
                </div>

                <div className="score-center">
                  <span className="score-num">{ctrl.score.red}</span>
                  <span className="score-sep">-</span>
                  <span className="score-num">{ctrl.score.blue}</span>
                </div>

                <div className="team">
                  <div className="team-badge blue">🔵</div>
                  <span className="team-name">Bleu</span>
                  <div className="team-players">
                    {ctrl.match.blue.length > 0
                      ? ctrl.match.blue.map((p, i) => (
                          <span key={i} className="team-player">{p.display_name || p.username}</span>
                        ))
                      : <span className="team-player">—</span>
                    }
                  </div>
                </div>
              </div>

              <div>
                <span className={`status-tag${ctrl.status.type ? ' ' + ctrl.status.type : ''}`}>
                  {ctrl.status.text}
                </span>
              </div>

              {ctrl.eloData && (
                <div className="elo-row">
                  {(ctrl.eloData.mode === '1v1'
                    ? [
                        { label: 'ELO Rouge', delta: ctrl.eloData.red[0].delta },
                        { label: 'ELO Bleu',  delta: ctrl.eloData.blue[0].delta },
                      ]
                    : [
                        { label: ctrl.eloData.red[0].username,  delta: ctrl.eloData.red[0].delta },
                        { label: ctrl.eloData.red[1].username,  delta: ctrl.eloData.red[1].delta },
                        { label: ctrl.eloData.blue[0].username, delta: ctrl.eloData.blue[0].delta },
                        { label: ctrl.eloData.blue[1].username, delta: ctrl.eloData.blue[1].delta },
                      ]
                  ).map((item, i) => (
                    <div key={i} className="elo-item">
                      <span className="elo-label">{item.label}</span>
                      <span className={`elo-delta ${item.delta >= 0 ? 'pos' : 'neg'}`}>
                        {item.delta >= 0 ? '+' : ''}{item.delta}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div style={{ marginTop: '14px' }}>
              {ctrl.previewMode === 'empty' && (
                <div className="preview-empty">
                  <span className="icon">🎯</span>
                  <span className="hint">Lance la calibration<br />pour voir le terrain</span>
                </div>
              )}
              {ctrl.previewMode === 'image' && (
                <div className="preview-card">
                  <img src={ctrl.previewImage} alt="Aperçu calibration" />
                  {ctrl.previewHint && (
                    <div className="calibration-hint">
                      Terrain non détecté. Ajuste angle, hauteur et lumière, puis relance.
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>

          {/* Colonne droite : contrôles */}
          <div className="controls-col">

            <div>
              <div className="section-title">Connexion</div>
              <button className="btn-dark" onClick={ctrl.connect} disabled={ctrl.connecting}>
                🔌 Se connecter
              </button>
            </div>

            <div>
              <div className="section-title">Calibration terrain</div>
              <div className="btn-row">
                <button className="btn-red" onClick={ctrl.triggerCalibration}>
                  🎯 Calibrer
                </button>
                {ctrl.showCalibrationButtons && (
                  <>
                    <button className="btn-outline" onClick={ctrl.confirmCalibration}>
                      ✅ Prêt !
                    </button>
                    <button className="btn-outline" onClick={ctrl.triggerCalibration}>
                      🔄 Relancer
                    </button>
                  </>
                )}
              </div>
            </div>

            {ctrl.showStop && (
              <div>
                <div className="section-title">Match en cours</div>
                <button
                  className="btn-outline"
                  onClick={ctrl.stopMatch}
                  style={{ borderColor: '#e50914', color: '#e50914' }}
                >
                  ⏹ Arrêter le match
                </button>
              </div>
            )}

            {ctrl.showReplay && (
              <div>
                <div className="section-title">Nouvelle partie</div>
                <button className="btn-red" onClick={ctrl.replayMatch}>
                  🔁 Rejouer
                </button>
              </div>
            )}

          </div>
        </div>
      </div>
    </>
  );
}
