export default function AuthOverlay({ show, tab, error, loading, onTabSwitch, onSubmit, usernameRef, passwordRef, displayNameRef }) {
  if (!show) return null;
  return (
    <div className="auth-overlay">
      <div className="auth-card">
        <div className="auth-header">
          <div className="logo">KickAnalytics</div>
          <div className="subtitle">Connecte-toi pour accéder au jeu</div>
        </div>
        <div className="auth-tabs">
          <button className={`auth-tab${tab === 'login'    ? ' active' : ''}`} onClick={() => onTabSwitch('login')}>Connexion</button>
          <button className={`auth-tab${tab === 'register' ? ' active' : ''}`} onClick={() => onTabSwitch('register')}>Inscription</button>
        </div>
        <div className="auth-body">
          {error && <div className="auth-error show">{error}</div>}
          <div className="auth-field">
            <label className="auth-label">Pseudo</label>
            <input className="auth-input" ref={usernameRef} type="text" placeholder="ton_pseudo" autoComplete="username" autoCapitalize="none" />
          </div>
          {tab === 'register' && (
            <div className="auth-field">
              <label className="auth-label">Nom affiché</label>
              <input className="auth-input" ref={displayNameRef} type="text" placeholder="Ton Nom" />
            </div>
          )}
          <div className="auth-field">
            <label className="auth-label">Mot de passe</label>
            <input className="auth-input" ref={passwordRef} type="password" placeholder="••••••" autoComplete={tab === 'login' ? 'current-password' : 'new-password'} />
          </div>
          <button className="auth-submit" disabled={loading} onClick={onSubmit}>
            {loading ? '...' : tab === 'login' ? 'Se connecter' : "S'inscrire"}
          </button>
        </div>
      </div>
    </div>
  );
}
