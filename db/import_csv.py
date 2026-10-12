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
    try:
        return int(str(v).replace(",", "").strip())
    except ValueError:
        raise ValueError(f"{what} not a number: {v!r}")


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
    report: dict = {"kind": kind, "total": 0, "loaded": 0, "skipped": 0, "errors": []}
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        for i, row in enumerate(reader, start=2):  # 1-based + header
            report["total"] += 1
            try:
                obj = _build(kind, _mapped(row, mapping), id_prefix, id_pad, month_default)
                if not validate_only:
                    _upsert(s, kind, obj)
            except ValueError as e:
                report["skipped"] += 1
                report["errors"].append({"row": i, "error": str(e)})
                continue
            report["loaded"] += 1
        if not validate_only:
            s.commit()
    if validate_only:
        report["loaded"] = 0
    return report


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
        month = str(f.get("month") or month_default).strip()
        if not MONTH_RE.match(month):
            raise ValueError(f"bad month {month!r}")
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
