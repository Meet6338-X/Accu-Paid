import React, { useState } from 'react';
import { api } from './api.js';

export default function Ingest() {
  const [slip, setSlip] = useState({ emp_id: 'EMP_042', month: '2026-03', gross: '', tds: '', pf: '', net: '' });
  const [slipOut, setSlipOut] = useState(null);
  const [notice, setNotice] = useState('');
  const [noticeOut, setNoticeOut] = useState(null);
  const [err, setErr] = useState('');

  const num = (v) => (v === '' ? undefined : Number(v));
  const runSlip = async (e) => {
    e.preventDefault(); setErr('');
    try {
      setSlipOut(await api.slip({
        emp_id: slip.emp_id, month: slip.month,
        gross: num(slip.gross), tds: num(slip.tds), pf: num(slip.pf), net: num(slip.net),
      }));
    } catch (ex) { setErr(ex.detail || 'slip parse failed'); }
  };
  const runNotice = async (e) => {
    e.preventDefault(); setErr('');
    try { setNoticeOut(await api.notice(notice)); }
    catch (ex) { setErr(ex.detail || 'notice parse failed'); }
  };

  return (
    <section aria-label="Ingest slips and notices">
      <h2>Diff a slip. Parse a notice.</h2>
      {err && <p className="err" role="alert">{err}</p>}
      <div className="two">
        <form className="card" onSubmit={runSlip}>
          <h3>Salary slip diff</h3>
          <div className="grid2">
            <label>Employee<input value={slip.emp_id} onChange={(e) => setSlip({ ...slip, emp_id: e.target.value })} required /></label>
            <label>Month<input value={slip.month} onChange={(e) => setSlip({ ...slip, month: e.target.value })} required /></label>
            {[['gross', 'Gross'], ['tds', 'TDS'], ['pf', 'PF'], ['net', 'Net']].map(([k, label]) => (
              <label key={k}>{label}<input type="number" step="any" value={slip[k]}
                onChange={(e) => setSlip({ ...slip, [k]: e.target.value })} /></label>
            ))}
          </div>
          <button className="btn go" type="submit">Diff vs payroll</button>
          {slipOut && (
            Object.keys(slipOut.diffs || {}).length === 0
              ? <p className="ok-text">No diffs over INR 500 — slip matches payroll.</p>
              : <table className="diff">
                <thead><tr><th>Cell</th><th>Slip</th><th>Payroll</th><th>Diff</th></tr></thead>
                <tbody>{Object.entries(slipOut.diffs).map(([k, d]) => (
                  <tr key={k} className="flag"><td>{k}</td><td>{d.slip}</td><td>{d.payroll}</td><td>{d.diff}</td></tr>
                ))}</tbody>
              </table>
          )}
        </form>
        <form className="card" onSubmit={runNotice}>
          <h3>GST notice parse</h3>
          <label>Paste notice text
            <textarea rows={6} value={notice} onChange={(e) => setNotice(e.target.value)} required
              placeholder="Demand of Rs 45,200 under section 73 due 2026-05-15 for INV-2041." />
          </label>
          <button className="btn go" type="submit">Parse</button>
          {noticeOut && (
            <dl className="ents">
              <div><dt>demand</dt><dd><code>{String(noticeOut.demand_amount)}</code></dd></div>
              <div><dt>due</dt><dd><code>{String(noticeOut.due_date)}</code></dd></div>
              <div><dt>section</dt><dd><code>{String(noticeOut.section)}</code></dd></div>
              <div><dt>invoices</dt><dd><code>{(noticeOut.linked_invoices || []).join(', ') || '—'}</code></dd></div>
              <div><dt>proposal</dt><dd><span className={`badge ${noticeOut.proposal === 'HOLD' ? 'needs_approval' : 'answered'}`}>{noticeOut.proposal}</span></dd></div>
            </dl>
          )}
        </form>
      </div>
    </section>
  );
}
