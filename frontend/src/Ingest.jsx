import React, { useState } from 'react';
import { api } from './api.js';

const CSV_MAPS = {
  employees: '{\n  "emp_id": "emp_id",\n  "name": "name",\n  "dept": "dept",\n  "ctc": "ctc"\n}',
  payroll: '{\n  "emp_id": "emp_id",\n  "month": "month",\n  "gross": "gross",\n  "tds": "tds",\n  "pf": "pf",\n  "esi": "esi",\n  "net": "net"\n}',
  invoices: '{\n  "invoice_id": "invoice_id",\n  "vendor": "vendor",\n  "po_amount": "po_amount",\n  "invoiced_amount": "invoiced_amount",\n  "gstin": "gstin"\n}',
};

function CsvPanel() {
  const [kind, setKind] = useState('payroll');
  const [mapping, setMapping] = useState(CSV_MAPS.payroll);
  const [file, setFile] = useState(null);
  const [validateOnly, setValidateOnly] = useState(true);
  const [rep, setRep] = useState(null);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const pickKind = (k) => { setKind(k); setMapping(CSV_MAPS[k]); setRep(null); };
  const upload = async (e) => {
    e.preventDefault(); setErr(''); setRep(null);
    if (!file) { setErr('Choose a .csv file first.'); return; }
    setBusy(true);
    try {
      setRep(await api.csv({ kind, mapping, file, idPad: 3, validateOnly }));
    } catch (ex) { setErr(ex.detail || 'upload failed'); }
    finally { setBusy(false); }
  };
  return (
    <form className="card" onSubmit={upload}>
      <h3>Your CSV → database</h3>
      <p className="muted">Map your columns, preview with validate-only, then load. Bad rows are skipped with reasons. IDs like EMP42 auto-shape to EMP_042.</p>
      <div className="grid2">
        <label>Table
          <select value={kind} onChange={(e) => pickKind(e.target.value)}>
            <option value="payroll">payroll</option>
            <option value="employees">employees</option>
            <option value="invoices">invoices</option>
          </select>
        </label>
        <label>File<input type="file" accept=".csv" onChange={(e) => setFile(e.target.files[0] || null)} /></label>
      </div>
      <label>Column mapping (JSON: your column → AccuPaid field)
        <textarea rows={8} value={mapping} onChange={(e) => setMapping(e.target.value)} spellCheck={false} />
      </label>
      <label className="check"><input type="checkbox" checked={validateOnly}
        onChange={(e) => setValidateOnly(e.target.checked)} /> Validate only (preview, write nothing)</label>
      {err && <p className="err" role="alert">{err}</p>}
      <button className="btn go" type="submit" disabled={busy}>{busy ? 'Uploading…' : validateOnly ? 'Preview' : 'Load into database'}</button>
      {rep && (
        <p className={rep.skipped === 0 ? 'ok-text' : 'warn-text'}>
          {rep.loaded} loaded · {rep.skipped} skipped of {rep.total}
        </p>
      )}
      {rep && rep.errors && rep.errors.length > 0 && (
        <table className="diff">
          <thead><tr><th>Row</th><th>Why skipped</th></tr></thead>
          <tbody>{rep.errors.slice(0, 20).map((e, i) => (
            <tr key={i} className="flag"><td>{e.row}</td><td>{e.error}</td></tr>
          ))}</tbody>
        </table>
      )}
    </form>
  );
}

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
      <h2>Diff a slip. Parse a notice. Load your CSV.</h2>
      {err && <p className="err" role="alert">{err}</p>}
      <CsvPanel />
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
