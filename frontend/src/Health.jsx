import React, { useEffect, useState } from 'react';
import { api, API_BASE } from './api.js';

/* ── Health routes & gates ── */
const ROUTES = [
  ['GET /', () => api.root()],
  ['GET /health', () => api.health()],
  ['POST /chat', () => api.chat('Show payroll for EMP_007 for 2026-01.')],
  ['POST /ingest/notice', () => api.notice('Demand Rs 100 section 73 due 2026-05-15 INV-2044')],
];

const GATES = [
  ['Entity-WER (tail)', '≤ 7%', '0.000'],
  ['Worst-slice TCR', '≥ 65%', '1.000'],
  ['Unapproved commits', '0', '0'],
  ['P95 / avg tokens', '≤ 8s / 3500', '3.03s / 175'],
];

export default function Health({ health }) {
  const [pings, setPings] = useState([]);
  useEffect(() => {
    let live = true;
    (async () => {
      const rows = [];
      for (const [name, fn] of ROUTES) {
        const t0 = performance.now();
        try { await fn(); rows.push({ name, ok: true, ms: Math.round(performance.now() - t0) }); }
        catch (e) { rows.push({ name, ok: false, ms: null, err: e.detail || e.status }); }
      }
      if (live) setPings(rows);
    })();
    return () => { live = false; };
  }, []);

  return (
    <section aria-label="Backend health">
      <h2>Backend health <span className="muted">· {API_BASE}</span></h2>

      {/* LLM status card */}
      {health && (
        <div className="card" style={{ marginBottom: 12 }}>
          <div className="card-head">
            <span>LLM backend</span>
            <span className={`badge ${health.llm.primary === 'openrouter:configured' ? 'ok-text' : 'warn-text'}`}>
              {health.llm.primary} → {health.llm.fallback}
            </span>
          </div>
          <div className="card-content">
            <div className="stat"><span>Primary</span><strong>{health.llm.primary}</strong></div>
            <div className="stat"><span>Fallback</span><strong>{health.llm.fallback}</strong></div>
            <div className="stat"><span>Enhance</span><strong>{health.llm.enhance !== false ? 'on' : 'off'}</strong></div>
            {health.llm.last && (
              <div>
                <span>Last call</span>
                <strong>{health.llm.last.backend || '—'}</strong>
                <span>{health.llm.last.ms != null ? `${health.llm.last.ms} ms` : '—'}</span>
                <span>{health.llm.last.at || '—'}</span>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Endpoint cross-check */}
      <h3>Endpoint cross-check</h3>
      <table className="diff">
        <thead><tr><th>Route</th><th>Result</th><th>Latency</th></tr></thead>
        <tbody>{pings.map((p) => (
          <tr key={p.name} className={p.ok ? '' : 'flag'}>
            <td><code>{p.name}</code></td>
            <td>{p.ok ? 'OK' : `FAIL: ${p.err}`}</td>
            <td>{p.ms != null ? `${p.ms} ms` : '—'}</td>
          </tr>
        ))}</tbody>
      </table>

      {/* Release gates */}
      <h3>Release gates <span className="muted">(python evals/harness.py, 120/120)</span></h3>
      <table className="agent-gates">
        <thead><tr><th>Gate</th><th>Threshold</th><th>Measured</th></tr></thead>
        <tbody>{GATES.map(([g, t, m]) => (
          <tr key={g}><td>{g}</td><td>{t}</td><td><strong>{m}</strong></td></tr>
        ))}</tbody>
      </table>
    </section>
  );
}