import { useState } from 'react';

const SLOT_CONFIGS = {
  '2p': [
    { key: 'r0', team: 'red'  },
    { key: 'b0', team: 'blue' },
  ],
  '4p': [
    { key: 'r0', team: 'red'  },
    { key: 'r1', team: 'red'  },
    { key: 'b0', team: 'blue' },
    { key: 'b1', team: 'blue' },
  ],
};

const TABLE_LABELS = {
  free:        ['🟢 Free',             'Table available'],
  calibrating: ['🔵 Calibrating',      'Field calibration in progress'],
  playing:     ['🔴 Match in progress', 'Match in progress'],
};

export default function JouerSection({ currentUser, tableData, pendingInvite, acceptedUsernames, onAcceptInvite, onMatchStarted, onReset }) {
  const [mode, setMode]       = useState(null);
  const [values, setValues]   = useState({ r0: '', r1: '', b0: '', b1: '' });
  const [matchId, setMatchId] = useState(null);
  const [error, setError]     = useState('');
  const [loading, setLoading] = useState(false);

  const slots     = mode ? SLOT_CONFIGS[mode] : [];
  const redSlots  = slots.filter(sl => sl.team === 'red');
  const blueSlots = slots.filter(sl => sl.team === 'blue');

  const setValue    = (key, val) => setValues(prev => ({ ...prev, [key]: val }));
  const getU        = (key) => values[key].trim().toLowerCase();
  const invitesSent = matchId !== null;
  const allFilled   = slots.every(sl => values[sl.key].trim());

  const isSlotAccepted = (key) => {
    const u = getU(key);
    if (!u) return false;
    if (u === currentUser?.username) return true;
    return acceptedUsernames.has(u);
  };

  const allAccepted = invitesSent && slots.every(sl => isSlotAccepted(sl.key));

  const handleSend = async () => {
    if (invitesSent) return;
    if (!allFilled) { setError('Fill in all usernames before sending.'); return; }
    setError('');
    setLoading(true);
    const red  = redSlots.map(sl => getU(sl.key));
    const blue = blueSlots.map(sl => getU(sl.key));
    try {
      const res = await fetch('/api/matches/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ red_players: red, blue_players: blue }),
      });
      const data = await res.json();
      if (!res.ok) { setError(data.error || 'Erreur'); return; }
      setMatchId(data.match_id);
    } catch { setError('Network error.'); }
    finally { setLoading(false); }
  };

  const handleStart = async () => {
    if (!matchId) return;
    setLoading(true);
    try {
      const res = await fetch(`/api/matches/${matchId}/start`, { method: 'POST' });
      const data = await res.json();
      if (!res.ok) { setError(data.error || 'Error'); return; }
      onMatchStarted?.();
      document.cookie = 'ka_page_access=controller; Path=/; SameSite=Lax';
      window.location.href = '/controller';
    } catch { setError('Network error.'); }
    finally { setLoading(false); }
  };

  const handleCancel = () => {
    setMatchId(null);
    setMode(null);
    setValues({ r0: '', r1: '', b0: '', b1: '' });
    setError('');
    onReset?.();
  };

  return (
    <div className="section active">
      <div className="page-content" style={{ maxWidth: '520px' }}>

        {pendingInvite && (
          <div style={s.inviteBanner}>
            <div style={s.inviteTitle}>🎮 Invitation received</div>
            <div style={s.inviteText}>
              <b>{pendingInvite.created_by}</b> invited you to play<br />
              🔴 {pendingInvite.red_players.join(', ')}<br />
              🔵 {pendingInvite.blue_players.join(', ')}
            </div>
            <button className="btn-red" style={{ marginTop: '10px' }} onClick={onAcceptInvite}>
              Accept
            </button>
          </div>
        )}

        <div style={s.card}>
          <div style={s.cardTitle}>Create a match</div>

          {!invitesSent && (
            <div style={s.modeRow}>
              <button style={{ ...s.modeBtn, ...(mode === '2p' ? s.modeBtnActive : {}) }}
                onClick={() => { setMode('2p'); setError(''); }}>
                👤 1v1
              </button>
              <button style={{ ...s.modeBtn, ...(mode === '4p' ? s.modeBtnActive : {}) }}
                onClick={() => { setMode('4p'); setError(''); }}>
                👥 2v2
              </button>
            </div>
          )}

          {mode && (
            <>
              {error && <div className="auth-error show">{error}</div>}

              <div style={s.slotsWrap}>
                <div style={s.teamLabel('#c62828')}>🔴 Red</div>
                {redSlots.map(sl => (
                  <SlotRow key={sl.key}
                    value={values[sl.key]}
                    onChange={val => setValue(sl.key, val)}
                    onSend={handleSend}
                    disabled={invitesSent}
                    sent={invitesSent}
                    accepted={isSlotAccepted(sl.key)}
                    loading={loading}
                  />
                ))}

                <div style={{ ...s.teamLabel('#1565c0'), marginTop: '10px' }}>🔵 Blue</div>
                {blueSlots.map(sl => (
                  <SlotRow key={sl.key}
                    value={values[sl.key]}
                    onChange={val => setValue(sl.key, val)}
                    onSend={handleSend}
                    disabled={invitesSent}
                    sent={invitesSent}
                    accepted={isSlotAccepted(sl.key)}
                    loading={loading}
                  />
                ))}
              </div>

              {invitesSent && allAccepted && (
                <button className="btn-red" disabled={loading} onClick={handleStart} style={{ marginTop: '4px' }}>
                  {loading ? '…' : '🎮 Play'}
                </button>
              )}
              {invitesSent && !allAccepted && (
                <div style={s.waitingText}>⏳ Waiting for players…</div>
              )}

              <button style={s.btnCancel} onClick={handleCancel}>
                {invitesSent ? 'Cancel match' : 'Reset'}
              </button>
            </>
          )}
        </div>

        {tableData && (() => {
          const [pillLabel, subLabel] = TABLE_LABELS[tableData.state] || ['—', '—'];
          return (
            <div className={`table-card${tableData.state !== 'free' ? ' occupied' : ''}`} style={{ marginTop: '14px' }}>
              <div className="table-card-top">
                <div className="table-icon">⚽</div>
                <div>
                  <div className="table-title">Foosball</div>
                  <div className="table-subtitle">{subLabel}</div>
                </div>
                <div className={`table-status-pill ${tableData.state}`}>{pillLabel}</div>
              </div>
            </div>
          );
        })()}

      </div>
    </div>
  );
}

function SlotRow({ value, onChange, onSend, disabled, sent, accepted, loading }) {
  return (
    <div style={sr.row}>
      <input
        className="auth-input"
        style={sr.input}
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder="pseudo"
        disabled={disabled}
      />
      {!sent ? (
        <button
          style={{ ...sr.arrowBtn, opacity: value.trim() ? 1 : 0.35 }}
          onClick={onSend}
          disabled={loading || !value.trim()}
          title="Send invitations"
        >›</button>
      ) : (
        <span style={sr.statusIcon}>{accepted ? '✅' : '⏳'}</span>
      )}
    </div>
  );
}

const s = {
  card:          { background: 'var(--card)', borderRadius: '12px', padding: '18px', border: '1.5px solid var(--border)', display: 'flex', flexDirection: 'column', gap: '10px' },
  cardTitle:     { fontSize: '15px', fontWeight: 900, color: 'var(--text)' },
  modeRow:       { display: 'flex', gap: '8px' },
  modeBtn:       { flex: 1, padding: '10px 0', borderRadius: '8px', border: '1.5px solid var(--border)', background: 'var(--bg)', color: 'var(--muted)', fontWeight: 700, fontSize: '13px', cursor: 'pointer' },
  modeBtnActive: { background: 'var(--red)', color: '#fff', border: '1.5px solid var(--red)' },
  slotsWrap:     { display: 'flex', flexDirection: 'column', gap: '6px' },
  teamLabel:     (color) => ({ fontSize: '10px', fontWeight: 800, color, textTransform: 'uppercase', letterSpacing: '1px' }),
  waitingText:   { fontSize: '13px', color: 'var(--muted)', textAlign: 'center', fontWeight: 600 },
  btnCancel:     { background: 'none', border: 'none', color: 'var(--muted)', fontSize: '13px', cursor: 'pointer', textAlign: 'center', padding: '4px' },
  inviteBanner:  { background: 'var(--card)', border: '1.5px solid var(--red)', borderRadius: '12px', padding: '16px', marginBottom: '14px' },
  inviteTitle:   { fontSize: '14px', fontWeight: 900, color: 'var(--red)', marginBottom: '8px' },
  inviteText:    { fontSize: '13px', color: 'var(--text)', lineHeight: 1.6 },
};

const sr = {
  row:        { display: 'flex', alignItems: 'center', gap: '8px' },
  input:      { flex: 1, margin: 0 },
  arrowBtn:   { width: '36px', height: '36px', borderRadius: '50%', border: '1.5px solid var(--border)', background: 'var(--bg)', color: 'var(--text)', fontSize: '20px', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 900, flexShrink: 0 },
  statusIcon: { fontSize: '18px', flexShrink: 0, width: '36px', textAlign: 'center' },
};
