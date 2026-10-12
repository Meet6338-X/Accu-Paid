"""CSV importer — load YOUR data into AccuPaid tables with a validation report.

Kinds: employees | payroll | invoices. Unmapped CSV columns are ignored.
Every row is validated against the same strict contracts as the MCP tools;
bad rows are skipped with reasons, never half-loaded.

Fields per kind:
  employees: emp_id, name, dept, ctc, bank_redacted?
  payroll:   emp_id, month, gross, tds, pf, esi, lop_days?, overtime_hrs?, net
  invoices:  invoice_id, vendor, po_amount, invoiced_amount, gstin,
             gst_mismatch?, status?

Options:
  mapping:       {csv_column: field} (required; explicit beats guessing)
  id_prefix:     e.g. "EMP_" + id_pad 3 turns numeric 42 -> EMP_042
                 (invoices: "INV-" + id_pad 4 -> INV-2041)
  month_default: YYYY-MM used when payroll has no month column
  validate_only: report without writing

Returns {"kind", "total", "loaded", "skipped", "errors": [{row, error}]}.
"""

from __future__ import annotations

import csv
import io
import os
import re

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from db.models import Base, Employee, PayrollRow, VendorInvoice

EMP_ID_RE = re.compile(r"^[A-Z]+_[0-9]{3,6}$")
MONTH_RE = re.compile(r"^20\d{2}-(?:0[1-9]|1[0-2])$")
INV_ID_RE = re.compile(r"^INV-[0-9]{4,6}$")
GSTIN_RE = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")


def _num(v, what: str):
    if v is None or str(v).strip() == "":
        raise ValueError(f"{what} missing")
    s = str(v).strip().replace(",", "").replace("₹", "").replace("Rs.", "").replace("Rs", "").strip()
    try:
        return int(float(s))
    except ValueError:
        raise ValueError(f"{what} not a number: {v!r}")


MONTH_NAMES = {"jan": "01", "feb": "02", "mar": "03", "apr": "04", "may": "05", "jun": "06",
               "jul": "07", "aug": "08", "sep": "09", "oct": "10", "nov": "11", "dec": "12"}


def _shape_month(raw: str, default: str) -> str:
    """Accept 2026-03, 03/2026, Mar 2026, March-26, datetime/date objects."""
    if raw is None or str(raw).strip() == "":
        return default
    if hasattr(raw, "strftime"):
        return raw.strftime("%Y-%m")
    s = str(raw).strip()
    m = re.match(r"^(20\d{2})-(\d{2})(?:-\d{2})?$", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    m = re.match(r"^(\d{1,2})[/\-](20\d{2})$", s)
    if m:
        return f"{m.group(2)}-{int(m.group(1)):02d}"
    m = re.match(r"^([A-Za-z]+)[\s\-]*(\d{2,4})$", s)
    if m and m.group(1)[:3].lower() in MONTH_NAMES:
        yy = m.group(2)
        yy = f"20{yy}" if len(yy) == 2 else yy
        return f"{yy}-{MONTH_NAMES[m.group(1)[:3].lower()]}"
    return s  # validator reports it if still bad


def _bool(v) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "y")


def _shape_id(raw: str, prefix: str, pad: int) -> str:
    """Canonicalize IDs: EMP42/EMP 042/42 -> EMP_042, INV2041/2041 -> INV-2041."""
    s = re.sub(r"\s+", "", str(raw).strip().upper())
    m = re.match(r"^([A-Z]+)[_\-]*0*(\d{1,6})$", s)
    if m:
        sep = "_" if prefix.endswith("_") else "-"
        return f"{m.group(1)}{sep}{int(m.group(2)):0{pad}d}"
    if re.fullmatch(r"\d{1,6}", s):
        return f"{prefix}{int(s):0{pad}d}"
    return s


def _mapped(row: dict, mapping: dict) -> dict:
    return {field: row[col] for col, field in mapping.items() if col in row}


def import_csv(text: str, kind: str, mapping: dict, db_path: str = "accupaid.db",
               id_prefix: str = "", id_pad: int = 3, month_default: str = "",
               validate_only: bool = False) -> dict:
    if kind not in ("employees", "payroll", "invoices"):
        raise ValueError("kind must be employees|payroll|invoices")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("empty csv or missing header")
    return import_rows(list(reader), kind, mapping, db_path, id_prefix, id_pad,
                       month_default, validate_only)


def import_rows(rows: list[dict], kind: str, mapping: dict, db_path: str = "accupaid.db",
                id_prefix: str = "", id_pad: int = 3, month_default: str = "",
                validate_only: bool = False, job_id: str = "", filename: str = "",
                chunk: int = 200, file_sha: str = "", pii_mode: str = "report",
                progress_cb=None) -> dict:
    """Durable core: chunked commits + natural-key upserts + persisted job ledger.

    Production extras: within-file duplicate quarantine (first wins), unmapped
    column warnings, PII scan (report|redact), progress callback (Temporal
    activities heartbeat through it). Re-uploads are safe by construction.
    """
    import hashlib as _hl
    import json as _json
    import time as _time
    import uuid as _uuid

    from db.models import IngestJob
    from db.pii import apply_redact, scan_rows

    job_id = job_id or _uuid.uuid4().hex[:12]
    report: dict = {"job_id": job_id, "kind": kind, "total": 0, "loaded": 0,
                    "skipped": 0, "deduped": 0, "quarantined": [], "warnings": [],
                    "pii": {"mode": pii_mode, "findings": [], "redacted": 0}, "errors": []}
    from db.anyfile import SCHEMA as _SCHEMA

    unknown = set(mapping.values()) - set(_SCHEMA[kind])
    if unknown:
        raise ValueError(f"unknown {kind} fields in mapping: {sorted(unknown)} "
                         f"(valid: {_SCHEMA[kind]})")
    header = list(rows[0].keys()) if rows else []
    mapped_cols = set(mapping)
    report["warnings"] = [f"unmapped column {c!r} ignored" for c in header
                          if c not in mapped_cols][:20]
    if pii_mode in ("report", "redact"):
        scan = scan_rows(rows)
        report["pii"]["findings"] = scan["findings"]
        if pii_mode == "redact" and scan["pii_columns"]:
            # Never alter mapped amount/ID fields, even if header-matched.
            protected = {"emp_id", "invoice_id", "month", "gross", "tds", "pf", "esi",
                         "net", "lop_days", "overtime_hrs", "po_amount", "invoiced_amount",
                         "ctc", "gstin"}
            safe = [c for c in scan["pii_columns"] if mapping.get(c) not in protected]
            rows, n = apply_redact(rows, safe)
            report["pii"]["redacted"] = n
    seen: dict[str, str] = {}
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        for i, row in enumerate(rows, start=2):  # 1-based + header
            report["total"] += 1
            try:
                fields = _mapped(row, mapping)
                key = _natural_key(kind, fields, id_prefix, id_pad, month_default)
                fph = _hl.sha256(_json.dumps(fields, sort_keys=True, default=str).encode()).hexdigest()
                if key in seen and seen[key] != fph:
                    report["quarantined"].append({"row": i, "key": key,
                                                  "reason": "duplicate key, conflicting values (first wins)"})
                    report["skipped"] += 1
                    continue
                if key in seen:
                    report["deduped"] += 1
                    report["loaded"] += 1
                    continue
                seen[key] = fph
                obj = _build(kind, fields, id_prefix, id_pad, month_default)
                if not validate_only:
                    _upsert(s, kind, obj)
            except ValueError as e:
                report["skipped"] += 1
                if len(report["errors"]) < 200:
                    report["errors"].append({"row": i, "error": str(e)})
                continue
            report["loaded"] += 1
            if not validate_only and report["loaded"] % chunk == 0:
                s.commit()  # crash-safe: finished chunks survive, re-upload finishes rest
                if progress_cb:
                    progress_cb(report["loaded"], len(rows), "loading")
        if not validate_only:
            s.commit()
            status = "DONE"
        else:
            status = "DRYRUN"
        if validate_only:
            report["loaded"] = 0
        if progress_cb:
            progress_cb(report["loaded"], len(rows), "finalize")
        s.add(IngestJob(job_id=job_id, kind=kind, filename=filename[:256], status=status,
                        total=report["total"], loaded=report["loaded"],
                        skipped=report["skipped"],
                        report=_json.dumps(report, default=str)[:20000],
                        created_at=_time.strftime("%Y-%m-%dT%H:%M:%S"),
                        file_sha=file_sha, progress=100, stage="finalize", mode="inline"))
        s.commit()
    return report


def _natural_key(kind: str, fields: dict, prefix: str, pad: int, month_default: str = "") -> str:
    if kind == "employees":
        return "emp:" + _shape_id(fields.get("emp_id", ""), prefix or "EMP_", pad or 3)
    if kind == "payroll":
        month = fields.get("month") or month_default
        if hasattr(month, "strftime"):
            month = month.strftime("%Y-%m")
        return ("pay:" + _shape_id(fields.get("emp_id", ""), prefix or "EMP_", pad or 3)
                + "|" + str(month).strip())
    return "inv:" + _shape_id(fields.get("invoice_id", ""), prefix or "INV-", pad or 4)


def _upsert(s: Session, kind: str, obj) -> None:
    """Update-or-insert on natural keys (merge() only matches PKs)."""
    if kind == "employees":
        cur = s.execute(select(Employee).where(Employee.emp_id == obj.emp_id)).scalar_one_or_none()
        key = ("emp_id",)
    elif kind == "payroll":
        cur = s.execute(select(PayrollRow).where(PayrollRow.emp_id == obj.emp_id,
                                                 PayrollRow.month == obj.month)).scalar_one_or_none()
        key = ("emp_id", "month")
    else:
        cur = s.execute(select(VendorInvoice).where(
            VendorInvoice.invoice_id == obj.invoice_id)).scalar_one_or_none()
        key = ("invoice_id",)
    if cur is None:
        s.add(obj)
        return
    for col in obj.__table__.columns.keys():
        if col not in ("id", *key):
            setattr(cur, col, getattr(obj, col))


def _build(kind: str, f: dict, prefix: str, pad: int, month_default: str):
    if kind == "employees":
        emp = _shape_id(f.get("emp_id", ""), prefix or "EMP_", pad or 3)
        if not EMP_ID_RE.match(emp):
            raise ValueError(f"bad emp_id {f.get('emp_id')!r} -> {emp!r}")
        return Employee(emp_id=emp, name=str(f.get("name", "")).strip() or emp,
                        dept=str(f.get("dept", "")).strip() or "-",
                        ctc=_num(f.get("ctc"), "ctc"),
                        bank_redacted=str(f.get("bank_redacted", "XXXX-XXXX-0000"))[-14:])
    if kind == "payroll":
        emp = _shape_id(f.get("emp_id", ""), prefix or "EMP_", pad or 3)
        if not EMP_ID_RE.match(emp):
            raise ValueError(f"bad emp_id {f.get('emp_id')!r}")
        month = _shape_month(f.get("month"), month_default)
        if not MONTH_RE.match(month):
            raise ValueError(f"bad month {f.get('month')!r} -> {month!r}")
        vals = {k: _num(f.get(k), k) for k in ("gross", "tds", "pf", "esi", "net")}
        return PayrollRow(emp_id=emp, month=month, lop_days=int(f.get("lop_days") or 0),
                          overtime_hrs=float(f.get("overtime_hrs") or 0), **vals)
    inv = _shape_id(f.get("invoice_id", ""), prefix or "INV-", pad or 4)
    if not INV_ID_RE.match(inv):
        raise ValueError(f"bad invoice_id {f.get('invoice_id')!r} -> {inv!r}")
    gstin = str(f.get("gstin", "")).strip().upper()
    if not GSTIN_RE.match(gstin):
        raise ValueError(f"bad gstin {gstin!r}")
    return VendorInvoice(invoice_id=inv, vendor=str(f.get("vendor", "")).strip() or inv,
                         po_amount=_num(f.get("po_amount"), "po_amount"),
                         invoiced_amount=_num(f.get("invoiced_amount"), "invoiced_amount"),
                         gstin=gstin, gst_mismatch=_bool(f.get("gst_mismatch", "")),
                         status=str(f.get("status") or "PENDING").upper())
