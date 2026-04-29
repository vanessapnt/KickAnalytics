import { useState, useRef } from 'react';

export default function AuthPage({ onAuth }) {
  const [view, setView]       = useState('home'); // 'home' | 'login' | 'register'
  const [error, setError]     = useState('');
  const [loading, setLoading] = useState(false);

  const usernameRef    = useRef();
  const passwordRef    = useRef();
  const displayNameRef = useRef();

  const authSubmit = async () => {
    setError('');
    const username     = usernameRef.current?.value.trim().toLowerCase() || '';
    const password     = passwordRef.current?.value || '';
    const display_name = displayNameRef.current?.value.trim() || '';
    if (!username || !password) { setError('Remplis tous les champs.'); return; }
    if (view === 'register' && !display_name) { setError('Choisis un nom affiché.'); return; }
    if (view === 'register' && password.length < 6) { setError('Mot de passe trop court (6 min).'); return; }
    setLoading(true);
    try {
      const url  = view === 'login' ? '/api/auth/login' : '/api/auth/register';
      const body = view === 'login' ? { username, password } : { username, display_name, password };
      const res  = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      const data = await res.json();
      if (!res.ok) { setError(data.error || 'Erreur inconnue'); return; }
      localStorage.setItem('ka_user', JSON.stringify(data));
      onAuth();
    } catch { setError('Erreur réseau. Réessaie.'); }
    finally { setLoading(false); }
  };

  return (
    <div style={s.page}>
      <style>{`
        @keyframes demo-pulse { 0%,100%{box-shadow:0 0 0 0 rgba(255,255,255,0.4)} 50%{box-shadow:0 0 0 12px rgba(255,255,255,0)} }
        .ka-btn-demo:hover { transform: scale(1.02); }
        .ka-btn-auth:hover { background: rgba(255,255,255,0.15) !important; }
        .ka-input::placeholder { color: rgba(255,255,255,0.55); }
        .ka-input:focus { outline: none; border-color: rgba(255,255,255,0.7) !important; }
      `}</style>

      <div style={s.logo}>KickAnalytics</div>
      <p style={s.tagline}>Analyse de matchs de babyfoot en temps réel</p>

      {view === 'home' && (
        <div style={s.btnGroup}>
          <button className="ka-btn-auth" style={s.btnAuth} onClick={() => { setError(''); setView('login'); }}>
            Se connecter
          </button>
          <button className="ka-btn-auth" style={s.btnAuth} onClick={() => { setError(''); setView('register'); }}>
            S'inscrire
          </button>
          <button className="ka-btn-demo" style={s.btnDemo} onClick={() => { window.location.href = '/test_pipeline.html'; }}>
            <span style={s.demoIcon}>▶</span>
            <span>
              <span style={s.demoTitle}>Voir la démo</span>
              <span style={s.demoSub}>Visualisation d'un match analysé</span>
            </span>
          </button>
        </div>
      )}

      {(view === 'login' || view === 'register') && (
        <div style={s.form}>
          {error && <div style={s.error}>{error}</div>}
          <input className="ka-input" style={s.input} ref={usernameRef} type="text"
            placeholder="Pseudo" autoCapitalize="none" autoComplete="username" />
          {view === 'register' && (
            <input className="ka-input" style={s.input} ref={displayNameRef} type="text" placeholder="Nom affiché" />
          )}
          <input className="ka-input" style={s.input} ref={passwordRef} type="password" placeholder="Mot de passe"
            autoComplete={view === 'login' ? 'current-password' : 'new-password'}
            onKeyDown={e => e.key === 'Enter' && authSubmit()} />
          <button style={s.btnSubmit} disabled={loading} onClick={authSubmit}>
            {loading ? '...' : view === 'login' ? 'Se connecter' : "S'inscrire"}
          </button>
          <button style={s.btnBack} onClick={() => { setView('home'); setError(''); }}>← Retour</button>
        </div>
      )}
    </div>
  );
}

const s = {
  page:     { minHeight: '100vh', background: '#083879', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '32px 24px', fontFamily: 'sans-serif' },
  logo:     { fontSize: '36px', fontWeight: 900, color: 'white', letterSpacing: '-1px', marginBottom: '8px' },
  tagline:  { color: 'rgba(255,255,255,0.75)', fontSize: '14px', marginBottom: '48px', textAlign: 'center' },

  btnGroup: { display: 'flex', flexDirection: 'column', gap: '12px', width: '100%', maxWidth: '320px' },
  btnAuth:  { width: '100%', padding: '18px', borderRadius: '12px', background: 'rgba(255,255,255,0.1)', border: '1.5px solid rgba(255,255,255,0.35)', color: 'white', fontSize: '16px', fontWeight: 700, cursor: 'pointer', transition: 'background 0.15s', fontFamily: 'sans-serif' },
  btnDemo:  { width: '100%', padding: '20px 24px', borderRadius: '12px', background: 'white', border: 'none', color: '#083879', fontSize: '16px', fontWeight: 900, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '16px', animation: 'demo-pulse 2s infinite', transition: 'transform 0.15s', fontFamily: 'sans-serif', marginTop: '4px' },
  demoIcon:  { fontSize: '28px', lineHeight: 1 },
  demoTitle: { display: 'block', fontSize: '16px', fontWeight: 900, textAlign: 'left' },
  demoSub:   { display: 'block', fontSize: '12px', fontWeight: 500, color: 'rgba(229,9,20,0.65)', marginTop: '2px', textAlign: 'left' },

  form:     { display: 'flex', flexDirection: 'column', gap: '12px', width: '100%', maxWidth: '320px' },
  error:    { background: 'rgba(0,0,0,0.2)', color: 'white', borderRadius: '8px', padding: '8px 12px', fontSize: '13px' },
  input:    { padding: '14px', borderRadius: '10px', border: '1.5px solid rgba(255,255,255,0.25)', fontSize: '15px', fontFamily: 'sans-serif', background: 'rgba(255,255,255,0.15)', color: 'white' },
  btnSubmit:{ padding: '16px', background: 'white', color: '#083879', border: 'none', borderRadius: '10px', fontWeight: 900, fontSize: '15px', cursor: 'pointer', fontFamily: 'sans-serif' },
  btnBack:  { background: 'none', border: 'none', color: 'rgba(255,255,255,0.7)', fontSize: '13px', cursor: 'pointer', textAlign: 'center', fontFamily: 'sans-serif' },
};
