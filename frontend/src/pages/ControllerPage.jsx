import '../styles/controller.css';
import { useControllerWs } from '../hooks/useControllerWs';

export default function ControllerPage() {
  const ctrl = useControllerWs();

  return (
    <>
      <header className="ctrl-header">
        <div className="logo">KickAnalytics</div>
        <button className="back-link" onClick={ctrl.leaveController}>Back</button>
      </header>

      <div className="page-content">
        <div className="ctrl-layout">

          <div>
            <div className="score-card">
              <div className="match-meta">
                <span>Controller</span>
                <span>{ctrl.match.mode || '1v1'}</span>
              </div>

              <div className="score-row">
                <div className="team">
                  <div className="team-badge red">🔴</div>
                  <span className="team-name">Red</span>
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
                  <span className="team-name">Blue</span>
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
                        { label: 'Red ELO', delta: ctrl.eloData.red[0].delta },
                        { label: 'Blue ELO', delta: ctrl.eloData.blue[0].delta },
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
                  <span className="hint">Start calibration<br />to see the field</span>
                </div>
              )}
              {ctrl.previewMode === 'image' && (
                <div className="preview-card">
                  <img src={ctrl.previewImage} alt="Calibration preview" />
                  {ctrl.previewHint && (
                    <div className="calibration-hint">
                      Field not detected. Adjust angle, height and lighting, then retry.
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>

          <div className="controls-col">

            <div>
              <div className="section-title">Connection</div>
              <button className="btn-dark" onClick={ctrl.connect} disabled={ctrl.connecting}>
                🔌 Connect
              </button>
            </div>

            <div>
              <div className="section-title">Field calibration</div>
              <div className="btn-row">
                <button className="btn-red" onClick={ctrl.triggerCalibration}>
                  🎯 Calibrate
                </button>
                {ctrl.showCalibrationButtons && (
                  <>
                    <button className="btn-outline" onClick={ctrl.confirmCalibration}>
                      ✅ Ready!
                    </button>
                    <button className="btn-outline" onClick={ctrl.triggerCalibration}>
                      🔄 Retry
                    </button>
                  </>
                )}
              </div>
            </div>

            {ctrl.showStop && (
              <div>
                <div className="section-title">Match in progress</div>
                <button
                  className="btn-outline"
                  onClick={ctrl.stopMatch}
                  style={{ borderColor: '#1e2f45', color: '#e4e8f2' }}
                >
                  ⏹ Stop match
                </button>
              </div>
            )}

            {ctrl.showReplay && (
              <div>
                <div className="section-title">New match</div>
                <button className="btn-red" onClick={ctrl.replayMatch}>
                  🔁 Play again
                </button>
              </div>
            )}

          </div>
        </div>
      </div>
    </>
  );
}
