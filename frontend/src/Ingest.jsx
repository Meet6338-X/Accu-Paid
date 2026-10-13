import React, { useEffect, useState } from 'react';
import { api } from './api.js';

/* Column‑map presets – kept for reference / manual override */
const CSV_MAPS = {
  employees: '{"emp_id": "emp_id", "name": "name", "dept": "dept", "ctc": "ctc"}',
  payroll: '{"emp_id": "emp_id", "month": "month", "gross": "gross", "tds": "tds", "pf": "pf", "esi": "esi", "net": "net"}',
  invoices: '{"invoice_id": "invoice_id", "vendor": "vendor", "po_amount": "po_amount", "invoiced_amount": "invoiced_amount", "gstin": "gstin"}',
};

function Ingest() {
  const [kind, setKind] = useState('');        /* '' = auto-detect */
  const [mapping, setMapping] = useState('');  /* JSON blank = AI auto-map */
  const [file, setFile] = useState(null);
  const [validateOnly, setValidateOnly] = useState(true);
  const [pii, setPii] = useState('report');
  const [rep, setRep] = useState(null);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);

  /* ── pickKind ── */
  const pickKind = (k) => {
    setKind(k);
    setMapping(k ? CSV_MAPS[k] : '');
    setRep(null);
  };

  /* ── job progress poll ── */
  useEffect(() => {
    if (!rep || rep.status !== 'RUNNING') return;
    const id = setInterval(async () => {
      try {
        const j = await api.job(rep.job_id);
        setRep(j);
        if (j.status !== 'RUNNING') clearInterval(id);
      } catch { clearInterval(id); }
    }, 2000);
    return () => clearInterval(id);
  }, [rep && rep.job_id, rep && rep.status]);

  /* ── upload ── */
  const upload = async (e) => {
    e.preventDefault(); setErr(''); setRep(null);
    if (!file) {
      setErr('Choose a file first (.csv .xlsx .json .pdf .txt .md .pdf).');
      return;
    }
    setBusy(true);
    try {
      setRep(await api.anyfile({ kind, mapping, file, validateOnly, pii }));
    } catch (ex) {
      setErr(ex.detail || 'upload failed');
    } finally { setBusy(false); }
  };

  /* ── cancel job ── */
  const cancel = async () => {
    try {
      setRep({ ...(await api.cancelJob(rep.job_id)), job_id: rep.job_id });
    } catch (ex) {
      setErr(ex.detail || 'cancel failed');
    }
  };

  /* ── render job report ── */
  const jobStatus = rep && rep.status;
  const jobHeader = (
    <p className={rep.skipped === 0 ? 'ok-text' : 'warn-text'}>
      {rep.loaded} loaded · {rep.skipped} skipped of {rep.total} · via {rep.mapping_via} · job <code>{rep.job_id}</code>
    </p>
  );

  return (
    <form className="card ingest-card" onSubmit={upload}>
      <h3 className="ingest-header">Your file → database</h3>

      <p className="muted">
        Any payroll/HR/invoice file. Leave table + mapping blank for AI auto-detect
        (LLM, else offline heuristic). IDs like EMP42 auto-shape. Uploads are durable jobs –
        re-submit after a crash to finish safely. Only the rows that haven't loaded will be processed.
      </p>

      <div className="grid2">
        <label>Table (blank = auto)
          <select value={kind} onChange={(e) => pickKind(e.target.value)}>
            <option value="">auto-detect</option>
            <option value="payroll">payroll</option>
            <option value="employees">employees</option>
            <option value="invoices">invoices</option>
          </select>
        </label>

        <label>File<input type="file"
          accept=".csv,.xlsx,.xls,.json,.txt,.md,.pdf"
          onChange={(e) => setFile(e.target.files[0] || null)} />
        </label>
      </div>

      <label>Column mapping JSON (blank = AI auto-map)
        <textarea rows={6} value={mapping} onChange={(e) => setMapping(e.target.value)}
          spellCheck={false} placeholder='{"Employee ID": "emp_id", "Monthly Income": "gross"}'
        /></label>

      <label className="check">
        <input type="checkbox" checked={validateOnly}
          onChange={(e) => setValidateOnly(e.target.checked)} />
        Validate only (preview; writes nothing to DB)
      </label>

      <label>PII handling
        <select value={pii} onChange={(e) => setPii(e.target.value)}>
          <option value="report">report (flag only)</option>
          <option value="redact">redact (mask; amounts/IDs never touched)</option>
          <option value="off">off</option>
        </select>
      </label>

      {err && <p className="err" role="alert">{err}</p>}

      <button className="btn go" type="submit" disabled={busy}>
        {busy ? 'Uploading…' : validateOnly ? 'Preview' : 'Load into database'}
      </button>

      {/* ── Live job progress while RUNNING ── */}
      {rep && rep.status === 'RUNNING' && (
        <div>
          <p className="muted">running on Temporal… {rep.stage || 'queued'} {rep.progress || 0}%</p>
          <div className="ttl" aria-hidden="true">
            <span style={{ width: `${rep.progress || 0}%` }} />
          </div>
          <button className="btn ghost" type="button" onClick={cancel}>Cancel job</button>
        </div>
      )}

      {rep && rep.status === 'CANCELLED' && (
        <p className="warn-text">job cancelled — finished chunks survive, re-submit to finish.</p>
      )}

      {/* ── Final report ── */}
      {rep && rep.status !== 'RUNNING' && rep.status !== 'CANCELLED' && (
        <div>
          {jobHeader}

          {/* Quarantine table */}
          {rep.quarantined && rep.quarantined.length > 0 && (
            <table className="diff">
              <thead>
                <tr><th colSpan="3">Quarantine (first wins)</th></tr>
              </thead>
              <tbody>
                {rep.quarantined.slice(0, 20).map((q, i) => (
                  <tr key={i} className="flag">
                    <td>{q.row}</td>
                    <td><code>{q.key}</code></td>
                    <td>{q.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {/* Warnings */}
          {rep.warnings && rep.warnings.length > 0 && (
            <p className="muted">warnings: {rep.warnings.slice(0, 5).join(' · ')}</p>
          )}

          {/* PII findings */}
          {rep.pii && rep.pii.findings && rep.pii.findings.length > 0 && (
            <p className="warn-text">
              PII ({rep.pii.mode}, redacted {rep.pii.redacted || 0}):
              {rep.pii.findings.map((f) => `${f.column}:${f.type}×${f.count}`).join(', ')}
            </p>
          )}

          {/* Errors (skipped rows) */}
          {rep.errors && rep.errors.length > 0 && (
            <table className="diff">
              <thead>
                <tr><th>Row</th><th>Why skipped</th></tr>
              </thead>
              <tbody>
                {rep.errors.slice(0, 20).map((e, i) => (
                  <tr key={i} className="flag">
                    <td>{e.row}</td>
                    <td>{e.error}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* ── No job yet ── */}
      {!rep && (
        <p className="muted">No upload yet — drop a file or select one above.</p>
      )}
    </form>
  );
}

export default function IngestPage() {
  /* Separate component for the slip + notice forms that sit alongside CsvPanel */
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
      <Ingest />
      <div className="two">
        <form className="card" onSubmit={runSlip}>
          <h3>Salary slip diff</h3>
          <div className="grid2">
            <label>Employee<input value={slip.emp_id} onChange={(e) => setSlip({ ...slip, emp_id: e.target.value })} required /></label>
            <label>Month<input value={slip.month} onChange={(e) => setSlip({ ...slip, month: e.target.value })} required /></label>
            {['gross', 'tds', 'pf', 'net'].map((k) => (
              <label key={k}>{k.charAt(0).toUpperCase() + k.slice(1)}<input type="number" step="any" value={slip[k]}
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
              <div><dt>proposal</dt><dd><span className={`badge ${noticeOut.proposal === 'HOLD' ? 'needs_approval' : 'answered'}`}>
                {noticeOut.proposal}</span></dd></div>
            </dl>
          )}
        </form>
      </div>
    </section>
  );
}