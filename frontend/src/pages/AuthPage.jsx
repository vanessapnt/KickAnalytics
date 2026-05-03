import { useState, useRef } from 'react';
import { useNavigate } from 'react-router-dom';

function compressAvatar(file, cb) {
  const img = new Image();
  img.onload = () => {
    const canvas = document.createElement('canvas');
    canvas.width = 256; canvas.height = 256;
    const ctx = canvas.getContext('2d');
    const min = Math.min(img.width, img.height);
    ctx.drawImage(img, (img.width - min) / 2, (img.height - min) / 2, min, min, 0, 0, 256, 256);
    cb(canvas.toDataURL('image/jpeg', 0.82));
  };
  img.src = URL.createObjectURL(file);
}

export default function AuthPage({ onAuth }) {
  const navigate = useNavigate();
  const [view, setView]       = useState('home');
  const [error, setError]     = useState('');
  const [loading, setLoading] = useState(false);
  const [avatar, setAvatar]   = useState(null);

  const usernameRef    = useRef();
  const passwordRef    = useRef();
  const displayNameRef = useRef();
  const fileRef        = useRef();

  const handleFile = (e) => {
    const f = e.target.files[0];
    if (f) compressAvatar(f, setAvatar);
    e.target.value = '';
  };

  const authSubmit = async () => {
    setError('');
    const username     = usernameRef.current?.value.trim().toLowerCase() || '';
    const password     = passwordRef.current?.value || '';
    const display_name = displayNameRef.current?.value.trim() || '';
    if (!username || !password) { setError('Fill in all fields.'); return; }
    if (view === 'register' && !display_name) { setError('Choose a display name.'); return; }
    if (view === 'register' && password.length < 6) { setError('Password too short (6 min).'); return; }
    setLoading(true);
    try {
      const url  = view === 'login' ? '/api/auth/login' : '/api/auth/register';
      const body = view === 'login'
        ? { username, password }
        : { username, display_name, password, avatar: avatar || null };
      const res  = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      const data = await res.json();
      if (!res.ok) { setError(data.error || 'Unknown error'); return; }
      localStorage.setItem('ka_user', JSON.stringify(data));
      onAuth();
    } catch { setError('Network error. Please try again.'); }
    finally { setLoading(false); }
  };

  const back = () => { setView('home'); setError(''); setAvatar(null); };

  return (
    <div style={s.page}>
      <style>{`
        @keyframes demo-pulse { 0%,100%{box-shadow:0 0 0 0 rgba(255,255,255,0.4)} 50%{box-shadow:0 0 0 12px rgba(255,255,255,0)} }
        .ka-btn-demo:hover { transform: scale(1.02); }
        .ka-btn-auth:hover { background: rgba(255,255,255,0.15) !important; }
        .ka-input::placeholder { color: rgba(255,255,255,0.55); }
        .ka-input:focus { outline: none; border-color: rgba(255,255,255,0.7) !important; }
        .ka-avatar-pick:hover { border-color: rgba(255,255,255,0.7) !important; }
      `}</style>

      <div style={s.logo}>KickAnalytics</div>
      <p style={s.tagline}>Real-time foosball match analysis</p>

      {view === 'home' && (
        <div style={s.btnGroup}>
          <button className="ka-btn-auth" style={s.btnAuth} onClick={() => { setError(''); setView('login'); }}>Sign in</button>
          <button className="ka-btn-auth" style={s.btnAuth} onClick={() => { setError(''); setView('register'); }}>Sign up</button>
          <button className="ka-btn-demo" style={s.btnDemo} onClick={() => navigate('/testpipeline')}>
            <span style={s.demoIcon}>▶</span>
            <span>
              <span style={s.demoTitle}>Watch the demo</span>
              <span style={s.demoSub}>Visualize an analyzed match</span>
            </span>
          </button>
        </div>
      )}

      {(view === 'login' || view === 'register') && (
        <div style={s.form}>
          {error && <div style={s.error}>{error}</div>}

          {view === 'register' && (
            <div style={s.avatarRow}>
              <div
                className="ka-avatar-pick"
                style={{ ...s.avatarPick, backgroundImage: avatar ? `url(${avatar})` : 'none' }}
                onClick={() => fileRef.current?.click()}
              >
                {!avatar && (
                  <>
                    <span style={{ fontSize: 26 }}>📷</span>
                    <span style={s.avatarHint}>Add photo</span>
                  </>
                )}
              </div>
              {avatar && (
                <button style={s.avatarRemove} onClick={() => setAvatar(null)}>✕ Remove</button>
              )}
              <input ref={fileRef} type="file" accept="image/*" style={{ display: 'none' }} onChange={handleFile} />
              <span style={s.avatarOpt}>optional</span>
            </div>
          )}

          <input className="ka-input" style={s.input} ref={usernameRef} type="text"
            placeholder="Username" autoCapitalize="none" autoComplete="username" />
          {view === 'register' && (
            <input className="ka-input" style={s.input} ref={displayNameRef} type="text" placeholder="Display name" />
          )}
          <input className="ka-input" style={s.input} ref={passwordRef} type="password" placeholder="Password"
            autoComplete={view === 'login' ? 'current-password' : 'new-password'}
            onKeyDown={e => e.key === 'Enter' && authSubmit()} />
          <button style={s.btnSubmit} disabled={loading} onClick={authSubmit}>
            {loading ? '...' : view === 'login' ? 'Sign in' : 'Sign up'}
          </button>
          <button style={s.btnBack} onClick={back}>← Back</button>
        </div>
      )}
    </div>
  );
}

const s = {
  page:      { minHeight: '100vh', background: '#0e1520', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '32px 24px', fontFamily: 'sans-serif' },
  logo:      { fontSize: '36px', fontWeight: 900, color: 'white', letterSpacing: '-1px', marginBottom: '8px' },
  tagline:   { color: 'rgba(255,255,255,0.75)', fontSize: '14px', marginBottom: '48px', textAlign: 'center' },
  btnGroup:  { display: 'flex', flexDirection: 'column', gap: '12px', width: '100%', maxWidth: '320px' },
  btnAuth:   { width: '100%', padding: '18px', borderRadius: '12px', background: 'rgba(255,255,255,0.1)', border: '1.5px solid rgba(255,255,255,0.35)', color: 'white', fontSize: '16px', fontWeight: 700, cursor: 'pointer', transition: 'background 0.15s', fontFamily: 'sans-serif' },
  btnDemo:   { width: '100%', padding: '20px 24px', borderRadius: '12px', background: 'white', border: 'none', color: '#1e2f45', fontSize: '16px', fontWeight: 900, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '16px', animation: 'demo-pulse 2s infinite', transition: 'transform 0.15s', fontFamily: 'sans-serif', marginTop: '4px' },
  demoIcon:  { fontSize: '28px', lineHeight: 1 },
  demoTitle: { display: 'block', fontSize: '16px', fontWeight: 900, textAlign: 'left' },
  demoSub:   { display: 'block', fontSize: '12px', fontWeight: 500, color: 'rgba(229,9,20,0.65)', marginTop: '2px', textAlign: 'left' },
  form:      { display: 'flex', flexDirection: 'column', gap: '12px', width: '100%', maxWidth: '320px' },
  error:     { background: 'rgba(0,0,0,0.2)', color: 'white', borderRadius: '8px', padding: '8px 12px', fontSize: '13px' },
  input:     { padding: '14px', borderRadius: '10px', border: '1.5px solid rgba(255,255,255,0.25)', fontSize: '15px', fontFamily: 'sans-serif', background: 'rgba(255,255,255,0.15)', color: 'white' },
  btnSubmit: { padding: '16px', background: 'white', color: '#1e2f45', border: 'none', borderRadius: '10px', fontWeight: 900, fontSize: '15px', cursor: 'pointer', fontFamily: 'sans-serif' },
  btnBack:   { background: 'none', border: 'none', color: 'rgba(255,255,255,0.7)', fontSize: '13px', cursor: 'pointer', textAlign: 'center', fontFamily: 'sans-serif' },
  avatarRow: { display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '6px' },
  avatarPick:{ width: 80, height: 80, borderRadius: '50%', background: 'rgba(255,255,255,0.1)', border: '2px dashed rgba(255,255,255,0.4)', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', cursor: 'pointer', overflow: 'hidden', backgroundSize: 'cover', backgroundPosition: 'center', transition: 'border-color 0.15s' },
  avatarHint:{ fontSize: '10px', color: 'rgba(255,255,255,0.7)', marginTop: '4px', fontFamily: 'sans-serif' },
  avatarRemove:{ background: 'none', border: 'none', color: 'rgba(255,255,255,0.55)', fontSize: '12px', cursor: 'pointer', fontFamily: 'sans-serif' },
  avatarOpt: { fontSize: '11px', color: 'rgba(255,255,255,0.35)', fontFamily: 'sans-serif' },
};
