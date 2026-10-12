"""Any-file ingest — xlsx/xls/csv/json/txt/md/pdf to row-tables + mapping inference.

Mapping precedence: explicit `mapping` arg > LLM inference (OpenRouter ->
Pollinations) > offline heuristic aliases > error asking for a mapping.
Unstructured text/pdf needs the LLM to structure rows; without a model it
returns a clear 422 instead of guessing.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re

SUPPORTED = (".csv", ".xlsx", ".xls", ".json", ".txt", ".md", ".pdf")

SCHEMA = {
    "employees": ["emp_id", "name", "dept", "ctc", "bank_redacted"],
    "payroll": ["emp_id", "month", "gross", "tds", "pf", "esi", "lop_days",
                "overtime_hrs", "net"],
    "invoices": ["invoice_id", "vendor", "po_amount", "invoiced_amount",
                 "gstin", "gst_mismatch", "status"],
}

_ALIASES = {
    "emp_id": {"employeeid", "empid", "empno", "empno.", "employeenumber", "employee number",
               "emp id", "id", "empcode", "staffid"},
    "name": {"employeename", "employee name", "name", "fullname", "full name", "staffname"},
    "dept": {"department", "dept", "team", "division"},
    "ctc": {"ctc", "annualsalary", "annual salary", "package", "annualctc"},
    "month": {"month", "paymonth", "pay month", "period", "salarymonth", "salary month", "date"},
    "gross": {"gross", "grosssalary", "gross salary", "monthlyincome", "monthly income", "salary",
              "income", "basic", "totalearnings"},
    "tds": {"tds", "tax", "incometax", "taxdeducted"},
    "pf": {"pf", "providentfund", "provident fund", "epf"},
    "esi": {"esi", "esic", "insurance"},
    "lop_days": {"lop", "lopdays", "lop days", "absentdays", "absent days", "unpaidleave"},
    "overtime_hrs": {"overtime", "overtimehrs", "overtime hrs", "othours", "extrahours"},
    "net": {"net", "netpay", "net pay", "inhand", "in hand", "takehome", "take home", "net salary"},
    "invoice_id": {"invoiceid", "invoice id", "invno", "inv no", "invoice", "invoiceno",
                   "billno", "bill no", "bill"},
    "vendor": {"vendor", "supplier", "party", "vendorname"},
    "po_amount": {"poamount", "po amount", "po", "orderamount", "order amount"},
    "invoiced_amount": {"invoicedamount", "invoiced amount", "billamount", "bill amount",
                        "amount", "invoiceamount", "total"},
    "gstin": {"gstin", "gst no", "gstno", "gst number", "gstnumber", "taxid"},
    "gst_mismatch": {"gstmismatch", "gst mismatch", "mismatch"},
    "status": {"status", "state", "stage"},
}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def parse_file(filename: str, data: bytes) -> list[dict]:
    ext = os.path.splitext(filename.lower())[1]
    if ext not in SUPPORTED:
        raise ValueError(f"unsupported {ext or '?'} — send one of {', '.join(SUPPORTED)}")
    if ext == ".csv":
        reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig")))
        return [dict(r) for r in reader]
    if ext in (".xlsx", ".xls"):
        try:
            import openpyxl
        except ImportError as e:
            raise ValueError("excel needs openpyxl (pip install openpyxl)") from e
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows or not rows[0]:
            raise ValueError("empty sheet")
        heads = [str(h).strip() if h is not None else f"col{i}" for i, h in enumerate(rows[0])]
        return [{h: (c.strftime("%Y-%m-%d") if hasattr(c, "strftime") else c)
                 for h, c in zip(heads, r)} for r in rows[1:] if any(v is not None and v != "" for v in r)]
    if ext == ".json":
        obj = json.loads(data.decode("utf-8-sig"))
        if isinstance(obj, dict):
            obj = obj.get("rows") or obj.get("data") or obj.get("items") or []
        if not isinstance(obj, list) or not obj:
            raise ValueError("json must be a list of objects (or {rows:[...]})")
        return [{str(k): (v if isinstance(v, (str, int, float)) or v is None else str(v))
                 for k, v in r.items()} for r in obj if isinstance(r, dict)]
    if ext in (".txt", ".md"):
        return [{"line": line} for line in data.decode("utf-8-sig").splitlines() if line.strip()]
    # pdf: raw text lines; structuring happens in extract_rows_text (needs LLM)
    try:
        from pypdf import PdfReader
    except ImportError as e:
        raise ValueError("pdf needs pypdf (pip install pypdf)") from e
    text = "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(data)).pages)
    return [{"line": line} for line in text.splitlines() if line.strip()]


def detect_kind(rows: list[dict]) -> str:
    heads = {_norm(k) for r in rows[:5] for k in r}
    if heads & {"invoiceid", "invoiceno", "gstin", "billno", "invoicedamount", "billamount"}:
        return "invoices"
    if heads & {"ctc", "annualsalary", "package"}:
        return "employees"
    if heads & {"gross", "monthlyincome", "salary", "pf", "esi", "tds"}:
        return "payroll"
    raise ValueError("cannot detect table kind — pass kind=employees|payroll|invoices")


def heuristic_mapping(kind: str, rows: list[dict]) -> dict:
    heads = {c: _norm(c) for r in rows[:5] for c in r}
    inv = {v: k for k, v in heads.items()}
    mapping = {}
    for field in SCHEMA[kind]:
        for col, n in heads.items():
            if n in _ALIASES.get(field, set()) or n == _norm(field):
                mapping[col] = field
                break
    _ = inv
    return mapping


def infer_mapping(kind: str | None, rows: list[dict]) -> tuple[str, dict, str]:
    """Return (kind, mapping, via). LLM first, heuristic fallback."""
    kind = kind or detect_kind(rows)
    if kind not in SCHEMA:
        raise ValueError("kind must be employees|payroll|invoices")
    if not rows:
        raise ValueError("no rows parsed")
    sample = rows[:3]
    try:
        from llm.client import complete

        prompt = ("Map CSV columns to fields. Reply STRICT JSON {column: field} only.\n"
                  f"Fields: {SCHEMA[kind]}\nColumns: {list(sample[0].keys())}\n"
                  f"Sample rows: {json.dumps(sample, default=str)[:1500]}")
        out = complete([{"role": "user", "content": prompt}], max_tokens=256, temperature=0)
        if out:
            m = re.search(r"\{.*\}", out, re.S)
            mapping = json.loads(m.group(0)) if m else {}
            mapping = {c: f for c, f in mapping.items()
                       if c in sample[0] and f in SCHEMA[kind]}
            if mapping:
                return kind, mapping, "llm"
    except Exception:
        pass
    mapping = heuristic_mapping(kind, rows)
    if not mapping:
        raise ValueError("could not map columns — pass an explicit mapping "
                         f"(fields: {SCHEMA[kind]})")
    return kind, mapping, "heuristic"


def extract_rows_text(rows: list[dict], kind: str) -> list[dict]:
    """Structure line-rows (txt/md/pdf) into records via LLM. Needs a model."""
    from llm.client import complete

    text = "\n".join(str(r.get("line", "")) for r in rows[:60])
    prompt = ("Extract records as a JSON array of objects with keys from "
              f"{SCHEMA[kind]}. Reply JSON array only.\nText:\n{text[:6000]}")
    out = complete([{"role": "user", "content": prompt}], max_tokens=1500, temperature=0)
    if not out:
        raise ValueError("unstructured text needs a model: set OPENROUTER_API_KEY "
                         "(or use network for the Pollinations fallback), else send csv/xlsx/json")
    m = re.search(r"\[.*\]", out, re.S)
    data = json.loads(m.group(0)) if m else []
    if not isinstance(data, list) or not data:
        raise ValueError("model returned no records — send csv/xlsx/json instead")
    return [r for r in data if isinstance(r, dict)]
