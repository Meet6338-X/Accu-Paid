import React, { useEffect, useState } from 'react';
import { api } from './api.js';

export function download(name, text, type = 'text/csv') {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([text], { type }));
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}

export default function Runs({ jumpRun }) {
  const [id, setId] = useState('');
  const [state, setState] = useState(null);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);

  const load = async (runId) => {
    const rid = (runId ?? id).trim();
    if (!rid || busy) return;
    setBusy(true); setErr(''); setState(null);
    try { setState(await api.run(rid)); }
    catch (e) { setErr(e.status === 404 ? 'unknown run_id' : (e.detail || 'lookup failed')); }
    finally { setBusy(false); }
  };

  useEffect(() => { if (jumpRun) { setId(jumpRun.runId); load(jumpRun.runId); } }, [jumpRun]);

  const st = state && state.state;
  const steps = st ? [
    ['query', st.query], ['route', st.route],
    ['entities', st.entities && JSON.stringify(st.entities)],
    ['tool', st.tool_name], ['risk', st.risk && `${st.risk.verdict} — ${(st.risk.reasons || []).join(', ')}`],
    ['verdict', st.human_verdict], ['result', st.result && st.result.status],
  ].filter(([, v]) => v) : [];

  return (
    <section aria-label="Run replay">
      <h2>Replay any run from checkpoint</h2>
      <form className="composer" onSubmit={(e) => { e.preventDefault(); load(); }}>
        <label className="sr" htmlFor="run-in">Run ID</label>
        <input id="run-in" value={id} onChange={(e) => setId(e.target.value)} placeholder="e.g. 709250da1735" />
        <button className="btn go" type="submit" disabled={busy}>{busy ? '…' : 'Replay'}</button>
      </form>
      {err && <p className="err" role="alert">{err}</p>}
      {st && (
        <div className="card">
          <ol className="timeline">
            {steps.map(([k, v]) => (
              <li key={k}><strong>{k}</strong><span>{String(v)}</span></li>
            ))}
          </ol>
          {st.citations && st.citations.length > 0 && (
            <p className="cites">cites: {st.citations.map((c) => <code key={c}>{c}</code>)}</p>
          )}
          <div className="row">
            <button className="btn ghost" onClick={async () => {
              const a = await api.audit(state.run_id, 'csv');
              download(`${state.run_id}_audit.csv`, a.csv);
            }}>Download audit CSV</button>
          </div>
        </div>
      )}
    </section>
  );
}
