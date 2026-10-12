"""PII scan + redact for ingest. Conservative by design.

Scanned: string cells in header-hinted columns (pan/aadhaar/account/bank/
phone/email/address/passport) PLUS strict PAN format anywhere. Amounts and IDs
are never touched: digit-runs only count inside hinted columns.

Modes: report (flag only) | redact (mask middle, keep last 4) | off.
"""

from __future__ import annotations

import re

PAN_RE = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")
AADHAAR_RE = re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}\b")
ACCT_RE = re.compile(r"\b\d{9,18}\b")
EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b")
PHONE_RE = re.compile(r"\b[6-9]\d{9}\b")

HINTS = ("pan", "aadhaar", "aadhar", "account", "acct", "bank", "phone",
         "mobile", "email", "address", "passport")


def _hinted(col: str) -> bool:
    c = col.lower()
    return any(h in c for h in HINTS)


def scan_rows(rows: list[dict]) -> dict:
    """Return {findings: [{column, type, count}], pii_columns: [...]}."""
    hits: dict[tuple[str, str], int] = {}
    for r in rows:
        for col, val in r.items():
            if not isinstance(val, str) or not val.strip():
                continue
            v = val.strip()
            if PAN_RE.search(v):
                hits[(col, "PAN")] = hits.get((col, "PAN"), 0) + 1
            if not _hinted(col):
                continue
            if AADHAAR_RE.search(v):
                hits[(col, "AADHAAR")] = hits.get((col, "AADHAAR"), 0) + 1
            elif ACCT_RE.search(v):
                hits[(col, "ACCOUNT")] = hits.get((col, "ACCOUNT"), 0) + 1
            if EMAIL_RE.search(v):
                hits[(col, "EMAIL")] = hits.get((col, "EMAIL"), 0) + 1
            if PHONE_RE.search(v):
                hits[(col, "PHONE")] = hits.get((col, "PHONE"), 0) + 1
    cols = sorted({c for c, _ in hits})
    return {"findings": [{"column": c, "type": t, "count": n} for (c, t), n in
                         sorted(hits.items())],
            "pii_columns": cols}


def redact_value(v: str) -> str:
    """Mask all but the last 4 alphanumerics: 123456789012 -> ********9012."""
    chars = list(v)
    keep = 4
    out = []
    seen = 0
    for ch in reversed(chars):
        if ch.isalnum():
            out.append(ch if seen < keep else "*")
            seen += 1
        else:
            out.append(ch)
    return "".join(reversed(out))


def apply_redact(rows: list[dict], pii_columns: list[str]) -> tuple[list[dict], int]:
    n = 0
    cols = set(pii_columns)
    for r in rows:
        for col in cols & set(r):
            if isinstance(r[col], str) and r[col].strip():
                r[col] = redact_value(r[col])
                n += 1
    return rows, n
