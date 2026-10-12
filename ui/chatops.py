"""Slack/WhatsApp ChatOps stubs (pure functions, no server).
Approve links expire in 15 min (TTL 900s, HMAC-signed).
Idempotency: commits keyed by run_id+tool+hash(args); double-approve is a no-op.
"""
from __future__ import annotations

import time
from urllib.parse import urlencode

from mcp_server.guards import sign_approval, verify_approval

BASE = "http://localhost:8000"
TTL_SECONDS = 900


def build_approve_buttons(run_id: str, secret: str) -> dict:
    """Return {approve_url, reject_url} with run_id/verdict/reason/signature/ts."""
    ts = int(time.time())
    out = {}
    for verdict in ("approve", "reject"):
        sig = sign_approval(run_id, verdict, "", secret, ts)
        qs = urlencode({"run_id": run_id, "verdict": verdict, "reason": "",
                        "signature": sig, "ts": ts})
        key = "approve_url" if verdict == "approve" else "reject_url"
        out[key] = f"{BASE}/approve/click?{qs}"
    return out


def parse_button_click(params: dict, secret: str, ttl: int = TTL_SECONDS) -> tuple[str, str]:
    """Verify HMAC button params; return (run_id, verdict) or raise PermissionError."""
    try:
        run_id = str(params["run_id"])
        verdict = str(params["verdict"])
        reason = str(params.get("reason", ""))
        sig = str(params["signature"])
    except KeyError as e:
        raise PermissionError(f"missing param: {e}") from e
    if verdict not in ("approve", "reject"):
        raise PermissionError("verdict must be approve|reject")
    if not verify_approval(run_id, verdict, reason, sig, secret, ttl):
        raise PermissionError("invalid or expired approval signature")
    return run_id, verdict


def format_result_message(result: dict) -> str:
    """Short human-readable summary with cites for Slack/WhatsApp."""
    status = result.get("status", "unknown")
    route = result.get("route", "-")
    summary = result.get("summary") or result.get("message") or result.get("reason") or ""
    cites = "; ".join((result.get("cites") or [])[:5]) or "no cites"
    commit = result.get("commit")
    extra = f" | commit={commit}" if commit else ""
    lines = [f"AccuPaid *{status}* [{route}]{extra}", summary.strip(), f"cites: {cites}"]
    return "\n".join(line for line in lines if line)
