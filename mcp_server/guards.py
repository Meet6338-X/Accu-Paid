"""Shared guardrails: Hinglish normalization, deterministic risk gate, PII redaction,
HMAC approval signatures with 15-min expiry, idempotency keys.

Constitution (from Constitutional AI 2212.08073): NEVER commit money without
human_verdict == approve. No prompt may override this — enforcement is Python, not prose.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import time

# --- Hinglish normalization (runs before route_query) ---

HINGLISH_MAP = {
    "sallery": "salary", "seleri": "salary", "selary": "salary", "sallary": "salary",
    "cmpny": "company", "compny": "company",
    "jyada": "zyada", "jyaada": "zyada",
    "kata": "kata", "kati": "kata", "katee": "kata",
    "pgar": "pagar",
    "invois": "invoice", "bil": "invoice", "bill": "invoice",
}

EMP_RE = re.compile(r"\bEMP[\s_\-]*0*(\d{1,6})\b", re.I)  # EMP42, EMP_042, emp 42 -> EMP_042
INV_RE = re.compile(r"\bINV[\s_\-]*(\d{4,6})\b", re.I)  # INV2041, INV 2041 -> INV-2041
DATE_SLASH_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b")  # 03/04 trap


def normalize_emp(m: re.Match) -> str:
    return f"EMP_{int(m.group(1)):03d}"


def normalize_inv(m: re.Match) -> str:
    return f"INV-{m.group(1)}"


def normalize_query(q: str) -> tuple[str, dict]:
    """Return (normalized_text, flags). Never guess DD/MM vs MM/DD — flag it."""
    flags: dict = {}
    low = q.lower()
    for k, v in HINGLISH_MAP.items():
        low = re.sub(rf"\b{re.escape(k)}\b", v, low)
    low, n1 = EMP_RE.subn(lambda m: normalize_emp(m), low)
    low, n2 = INV_RE.subn(lambda m: normalize_inv(m), low)
    m = DATE_SLASH_RE.search(q)
    if m:
        flags["ambiguous_date"] = m.group(0)
    flags.update({"emp_norm": n1 > 0, "inv_norm": n2 > 0})
    return low, flags


# --- Deterministic risk gate (after dry-run, before human_approval) ---

AMOUNT_THRESHOLD = 10000
NET_DELTA_THRESHOLD = 5000


def risk_gate(
    *,
    invoiced: float | None = None,
    po: float | None = None,
    gst_mismatch: bool = False,
    net_delta: float | None = None,
    ambiguous_date: bool = False,
) -> dict:
    reasons: list[str] = []
    if invoiced is not None and po is not None and abs(invoiced - po) > AMOUNT_THRESHOLD:
        reasons.append(f"amount_diff={abs(invoiced - po):g}>10000")
    if gst_mismatch:
        reasons.append("gst_mismatch=true")
    if net_delta is not None and abs(net_delta) > NET_DELTA_THRESHOLD:
        reasons.append(f"net_delta={net_delta:g}>5000")
    if ambiguous_date:
        reasons.append("ambiguous_date=DD/MM-vs-MM/DD")
    return {"needs_approval": bool(reasons), "reasons": reasons,
            "verdict": "HOLD" if reasons else "AUTO_OK"}


# --- PII redaction (before LangSmith log) ---

PAN_RE = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")
AADHAAR_RE = re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b")
BANK_RE = re.compile(r"\b\d{9,18}\b")


def redact_pii(text: str) -> str:
    text = PAN_RE.sub("[PAN]", text)
    text = AADHAAR_RE.sub("[AADHAAR]", text)
    text = BANK_RE.sub("[BANK]", text)
    return text


# --- HMAC approval signatures (15-min expiry) ---

def sign_approval(run_id: str, verdict: str, reason: str, secret: str, ts: int | None = None) -> str:
    ts = int(ts if ts is not None else time.time())
    msg = f"{run_id}|{verdict}|{reason}|{ts}".encode()
    sig = hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()
    return f"{ts}.{sig}"


def verify_approval(run_id: str, verdict: str, reason: str, signature: str,
                    secret: str, ttl: int = 900) -> bool:
    try:
        ts_s, sig = signature.split(".", 1)
        ts = int(ts_s)
    except ValueError:
        return False
    if abs(time.time() - ts) > ttl:
        return False
    expected = sign_approval(run_id, verdict, reason, secret, ts)
    return hmac.compare_digest(expected, signature)


def idempotency_key(run_id: str, tool: str, args: dict) -> str:
    canon = json.dumps(args, sort_keys=True, default=str)
    return hashlib.sha256(f"{run_id}|{tool}|{canon}".encode()).hexdigest()
