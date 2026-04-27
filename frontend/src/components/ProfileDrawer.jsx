export default function ProfileDrawer({ show, currentUser, stats, onClose, onLogout }) {
  if (!currentUser) return null;
  const letter = (currentUser.display_name || currentUser.username || '?')[0].toUpperCase();
  return (
    <>
      <div className={`profile-overlay${show ? ' open' : ''}`} onClick={onClose}></div>
      <div className={`profile-drawer${show ? ' open' : ''}`}>
        <div className="profile-drawer-header">
          <div className="profile-drawer-avatar">{letter}</div>
          <div>
            <div className="profile-drawer-name">{currentUser.display_name}</div>
            <div className="profile-drawer-user">@{currentUser.username}</div>
          </div>
          <button className="profile-drawer-close" onClick={onClose}>✕</button>
        </div>

        <div className="profile-drawer-body">
          {stats === null  && <div className="profile-empty">Chargement...</div>}
          {stats === false && <div className="profile-empty">Impossible de charger les stats.<br />Vérifie ta connexion.</div>}
          {stats && <ProfileStats stats={stats} currentUser={currentUser} />}
        </div>

        <div className="profile-drawer-footer">
          <button className="btn-logout-full" onClick={() => { onLogout(); onClose(); }}>Se déconnecter</button>
        </div>
      </div>
    </>
  );
}

function ProfileStats({ stats: d, currentUser }) {
  const wr    = d.winrate_pct != null ? d.winrate_pct + '%' : '—';
  const prec  = d.avg_precision_pct != null ? d.avg_precision_pct + '%' : '—';
  const poss  = d.avg_possession != null ? d.avg_possession + '%' : '—';
  const wins   = d.wins ?? 0;
  const played = d.matches_played ?? 0;
  return (
    <>
      <div className="profile-elo-banner">
        <div>
          <div className="profile-elo-label">ELO</div>
          <div className="profile-elo-val">{currentUser.elo}</div>
          <div className="profile-elo-sub">{played} match{played !== 1 ? 's' : ''} joué{played !== 1 ? 's' : ''}</div>
        </div>
      </div>
      <div className="profile-stats-grid">
        <div className="profile-stat-card"><div className="profile-stat-val">{wins}</div><div className="profile-stat-lbl">Victoires</div></div>
        <div className="profile-stat-card"><div className="profile-stat-val red">{wr}</div><div className="profile-stat-lbl">Win rate</div></div>
        <div className="profile-stat-card"><div className="profile-stat-val">{prec}</div><div className="profile-stat-lbl">Précision</div></div>
        <div className="profile-stat-card"><div className="profile-stat-val">{poss}</div><div className="profile-stat-lbl">Possession</div></div>
        <div className="profile-stat-card"><div className="profile-stat-val">{d.avg_max_speed != null ? d.avg_max_speed + ' km/h' : '—'}</div><div className="profile-stat-lbl">Vitesse max</div></div>
        <div className="profile-stat-card"><div className="profile-stat-val">{d.total_goals ?? '—'}</div><div className="profile-stat-lbl">Buts</div></div>
      </div>
      <div>
        <div className="profile-section-title">Derniers matchs</div>
        <div className="profile-history">
          {(!d.recent_matches || d.recent_matches.length === 0)
            ? <div className="profile-empty">Aucun match joué</div>
            : d.recent_matches.map((m, i) => {
                const cls    = m.draw ? 'draw' : m.won ? 'win' : 'loss';
                const lbl    = m.draw ? 'N' : m.won ? 'V' : 'D';
                const delta  = m.elo_delta ?? 0;
                const eloCls = delta > 0 ? 'pos' : delta < 0 ? 'neg' : 'neu';
                const eloStr = delta > 0 ? '+' + delta : delta === 0 ? '±0' : '' + delta;
                return (
                  <div key={i} className="profile-match-row">
                    <div className={`profile-match-result ${cls}`}>{lbl}</div>
                    <div>
                      <div className="profile-match-score">{m.score_my_team} - {m.score_opp}</div>
                      <div className="profile-match-meta">{m.mode || '1v1'} · {m.date ? new Date(m.date).toLocaleDateString('fr-FR') : '—'}</div>
                    </div>
                    <div className={`profile-match-elo ${eloCls}`}>{eloStr}</div>
                  </div>
                );
              })
          }
        </div>
      </div>
    </>
  );
}
