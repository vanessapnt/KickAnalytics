export default function AuthOverlay({ show, tab, error, loading, onTabSwitch, onSubmit, usernameRef, passwordRef, displayNameRef }) {
  if (!show) return null;
  return (
    <div className="auth-overlay">
      <div className="auth-card">
        <div className="auth-header">
          <div className="logo">KickAnalytics</div>
          <div className="subtitle">Sign in to access the game</div>
        </div>
        <div className="auth-tabs">
          <button className={`auth-tab${tab === 'login'    ? ' active' : ''}`} onClick={() => onTabSwitch('login')}>Sign in</button>
          <button className={`auth-tab${tab === 'register' ? ' active' : ''}`} onClick={() => onTabSwitch('register')}>Sign up</button>
        </div>
        <div className="auth-body">
          {error && <div className="auth-error show">{error}</div>}
          <div className="auth-field">
            <label className="auth-label">Username</label>
            <input className="auth-input" ref={usernameRef} type="text" placeholder="your_username" autoComplete="username" autoCapitalize="none" />
          </div>
          {tab === 'register' && (
            <div className="auth-field">
              <label className="auth-label">Display name</label>
              <input className="auth-input" ref={displayNameRef} type="text" placeholder="Your Name" />
            </div>
          )}
          <div className="auth-field">
            <label className="auth-label">Password</label>
            <input className="auth-input" ref={passwordRef} type="password" placeholder="••••••" autoComplete={tab === 'login' ? 'current-password' : 'new-password'} />
          </div>
          <button className="auth-submit" disabled={loading} onClick={onSubmit}>
            {loading ? '...' : tab === 'login' ? 'Sign in' : 'Sign up'}
          </button>
        </div>
      </div>
    </div>
  );
}
