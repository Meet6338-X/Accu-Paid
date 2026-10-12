import React, { useEffect, useRef, useState } from 'react';
import { api } from './api.js';

const STAGES = ['normalize', 'route', 'docs', 'execute', 'verify', 'risk', 'decision'];
const CHIPS = [
  'mera march ki salary kam ayi, TDS jyada kata? EMP_042',
  'Show payroll for EMP_007 for 2026-01.',
  'Apply EL leave for EMP_042 from 2026-04-10 to 2026-04-12.',
  'Parse this notice: demand of Rs 45,200 under section 73 due 2026-05-15 for INV-2041.',
  'Simulate TDS for CTC 1200000 under old vs new regime.',
];

const reduced = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;

const DEMO_QUERY = 'mera march ki salary kam ayi, TDS jyada kata? EMP_042';
const REASONS = ['verified with payroll sheet', 'checked with vendor', 'CA confirmed', 'typo, ignore'];

function useTypewriter(text, active) {
  const [out, setOut] = useState(active ? '' : text);
  useEffect(() => {
    if (!active || reduced()) { setOut(text); return; }
    setOut('');
    let i = 0;
    const id = setInterval(() => {
      i += 2;
      setOut(text.slice(0, i));
      if (i >= text.length) clearInterval(id);
    }, 18);
    return () => clearInterval(id);
  }, [text, active]);
  return out;
}

function Pipeline({ live, snapTo }) {
  const [n, setN] = useState(0);
  useEffect(() => {
    if (!live) { setN(snapTo != null ? snapTo : 0); return; }
    setN(0);
    const id = setInterval(() => setN((v) => Math.min(v + 1, STAGES.length - 1)), 260);
    return () => clearInterval(id);
  }, [live, snapTo]);
  return (
    <ol className="pipe" aria-label="Agent pipeline">
      {STAGES.map((s, i) => (
        <li key={s} className={i < n || (!live && i <= (snapTo ?? 99)) ? 'done' : i === n && live ? 'run' : ''}>
          <span className="dot" aria-hidden="true" />{s}
        </li>
      ))}
    </ol>
  );
}

function Confetti() {
  if (reduced()) return null;
  const bits = Array.from({ length: 26 }, (_, i) => i);
  return (
    <div className="confetti" aria-hidden="true">
      {bits.map((i) => <span key={i} style={{ '--d': `${(i * 37) % 360}deg`, '--x': `${(i * 53) % 220 - 110}px` }} />)}
    </div>
  );
}

function ResultCard({ result, animate }) {
  const summary = useTypewriter(result.summary || result.message || result.reason || '', animate);
  return (
    <div className="card">
      <div className="card-head">
        <span className={`badge ${result.status}`}>{result.status}</span>
        {result.route && <span className="muted">{result.route}</span>}
      </div>
      {summary && <p className="summary">{summary}</p>}
      {result.entities && (
        <dl className="ents">
          {Object.entries(result.entities).filter(([, v]) => v).map(([k, v]) => (
            <div key={k}><dt>{k}</dt><dd><code>{String(v)}</code></dd></div>
          ))}
        </dl>
      )}
      {result.risk && result.risk.reasons && result.risk.reasons.length > 0 && (
        <p className="muted">risk: {result.risk.reasons.join(' · ')}</p>
      )}
      {result.cites && result.cites.length > 0 && (
        <p className="cites">cites: {result.cites.map((c) => <code key={c}>{c}</code>)}</p>
      )}
      {result.commit && (
        <p className={result.commit.committed ? 'ok-text' : 'warn-text'}>
          {result.commit.committed ? 'committed ✓' : 'held: ' + (result.commit.note || '')}
        </p>
      )}
    </div>
  );
}

function Approval({ pending, onDone, coach }) {
  const [reason, setReason] = useState('');
  const [left, setLeft] = useState(pending.ttl_seconds || 900);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  useEffect(() => {
    const id = setInterval(() => setLeft((s) => Math.max(0, s - 1)), 1000);
    return () => clearInterval(id);
  }, []);
  const total = pending.ttl_seconds || 900;
  const decide = async (verdict, sig) => {
    setBusy(true); setErr('');
    try {
      const res = await api.approve(pending.run_id, verdict, reason, sig);
      onDone(res);
    } catch (e) { setErr(e.detail || 'approve failed'); setBusy(false); }
  };
  const mm = `${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')}`;
  return (
    <div className={`card approve${coach ? ' coach' : ''}`}>
      <div className="card-head">
        <span className="badge needs_approval">needs approval</span>
        <span className="muted" title="Signature expiry">expires in {mm}</span>
      </div>
      {coach && <p className="coach-hint" role="status">This is the gate — nothing commits until you press Approve. Try it.</p>}
      <div className="ttl" aria-hidden="true"><span style={{ width: `${(left / total) * 100}%` }} /></div>
      <ul>{pending.reasons.map((r) => <li key={r}><code>{r}</code></li>)}</ul>
      <label htmlFor="ap-reason">Reason (optional annotation)</label>
      <input id="ap-reason" value={reason} onChange={(e) => setReason(e.target.value)}
        placeholder="e.g. verified with payroll sheet" />
      <div className="chips">
        {REASONS.map((r) => <button key={r} className="chip" onClick={() => setReason(r)}>{r}</button>)}
      </div>
      {err && <p className="err" role="alert">{err}</p>}
      <div className="row">
        <button className="btn go" disabled={busy || left === 0} onClick={() => decide('approve', pending.approve_signature)}>
          {busy ? 'Sending…' : 'Approve'}
        </button>
        <button className="btn ghost" disabled={busy} onClick={() => decide('reject', pending.reject_signature)}>Reject</button>
      </div>
      {left === 0 && <p className="err" role="alert">Signature expired — ask again to get a fresh link.</p>}
    </div>
  );
}

export default function Chat({ remember }) {
  const [msgs, setMsgs] = useState([]);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [celebrate, setCelebrate] = useState(0);
  const [demoArmed, setDemoArmed] = useState(false);
  const bottom = useRef(null);
  useEffect(() => { bottom.current?.scrollIntoView({ behavior: reduced() ? 'auto' : 'smooth' }); }, [msgs]);

  const runDemo = () => { setDemoArmed(true); send(DEMO_QUERY); };

  const send = async (text) => {
    const q = (text ?? input).trim();
    if (!q || busy) return;
    setInput(''); setBusy(true);
    const id = Math.random().toString(36).slice(2);
    setMsgs((m) => [...m, { id, who: 'you', text: q }]);
    const workId = id + '-work';
    setMsgs((m) => [...m, { id: workId, who: 'bot', working: true }]);
    try {
      const res = await api.chat(q);
      setMsgs((m) => m.map((x) => x.id !== workId ? x : { ...x, working: false, data: res }));
      remember(res.run_id, res.status);
      if (res.status === 'committed') setCelebrate((c) => c + 1);
    } catch (e) {
      setMsgs((m) => m.map((x) => x.id !== workId ? x : { ...x, working: false, error: e.detail || 'request failed' }));
    } finally { setBusy(false); }
  };

  const resolveApproval = (workId, res) => {
    setMsgs((m) => m.map((x) => x.id !== workId ? x : { ...x, data: res }));
    remember(res.run_id, res.status);
    if (res.status === 'committed') setCelebrate((c) => c + 1);
  };

  return (
    <section aria-label="Chat">
      {celebrate > 0 && <Confetti key={celebrate} />}
      <div className="thread" aria-live="polite">
        {msgs.length === 0 && (
          <div className="empty">
            <svg className="empty-art" viewBox="0 0 120 90" aria-hidden="true">
              <rect x="8" y="10" width="104" height="70" rx="10" fill="none" stroke="currentColor" strokeWidth="2"/>
              <path d="M20 32h80M20 44h56M20 56h68" stroke="currentColor" strokeWidth="3" strokeLinecap="round" opacity=".55"/>
              <circle cx="92" cy="62" r="12" fill="none" stroke="currentColor" strokeWidth="2"/>
              <path d="M87 62l3.5 3.5L97 59" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
            </svg>
            <h2>Salary dispute aaya?</h2>
            <p className="muted">Watch a typo-filled Hinglish query turn into a cited dry-run — then you approve it. Live, in 60 seconds.</p>
            <button className="btn go big" onClick={runDemo} disabled={busy}>▶ Run the 60-second demo</button>
            <div className="statline" aria-label="Measured results">
              <span><strong>120/120</strong> evals</span>
              <span><strong>0</strong> unapproved</span>
              <span><strong>3.0s</strong> P95</span>
            </div>
          </div>
        )}
        {msgs.map((m) => m.who === 'you' ? (
          <p key={m.id} className="bubble you">{m.text}</p>
        ) : (
          <div key={m.id} className="bubble bot">
            {m.working && (<><Pipeline live /> <p className="muted">working the pipeline…</p></>)}
            {m.error && <p className="err" role="alert">{m.error}</p>}
            {m.data && m.data.status === 'needs_approval' && !m.data.result && (
              <Approval pending={m.data} coach={demoArmed} onDone={(res) => { setDemoArmed(false); resolveApproval(m.id, res); }} />
            )}
            {m.data && m.data.result && (<><Pipeline snapTo={99} /><ResultCard result={m.data.result} animate /></>)}
            {m.data && m.data.status === 'answered' && !m.data.result && <p className="muted">done.</p>}
          </div>
        ))}
        <div ref={bottom} />
      </div>
      <div className="chips" role="group" aria-label="Example queries">
        {CHIPS.map((c) => <button key={c} className="chip" disabled={busy} onClick={() => send(c)}>{c}</button>)}
      </div>
      <form className="composer" onSubmit={(e) => { e.preventDefault(); send(); }}>
        <label className="sr" htmlFor="chat-in">Ask AccuPaid</label>
        <input id="chat-in" value={input} onChange={(e) => setInput(e.target.value)}
          placeholder="e.g. mera march ki salary kam ayi? EMP_042" autoComplete="off" />
        <button className="btn go" type="submit" disabled={busy || !input.trim()}>
          {busy ? '…' : 'Send'}
        </button>
      </form>
    </section>
  );
}
