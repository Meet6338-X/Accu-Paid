"""LangGraph nodes — pure functions over AgentState (testable without langgraph).

Pipeline: normalize -> route -> fetch_docs -> execute_tool -> verify_node (CoVe)
           -> risk_gate -> [human_approval] -> format_response.
Context discipline: docs capped 1800 tokens (~7200 chars), tool outputs summarized
over 800 tokens (~3200 chars); Hindi 3x token fertility assumed in the budget.
"""

from __future__ import annotations

import os
import re

from mcp_server import server
from mcp_server.guards import DATE_SLASH_RE, normalize_query
from mcp_server.models import (
    LeaveApplyInput,
    NoticeParseInput,
    PayrollLookupInput,
    TdsSimulateInput,
    VendorInvoiceReconInput,
)

DOC_CHAR_CAP = 7200  # ~1800 tokens
TOOL_CHAR_CAP = 3200  # ~800 tokens

MONTH_MAP = {
    "january": "01", "jan": "01", "february": "02", "feb": "02", "march": "03",
    "mar": "03", "maarch": "03", "april": "04", "apr": "04", "may": "05",
    "june": "06", "jun": "06", "july": "07", "jul": "07", "august": "08",
    "aug": "08", "september": "09", "sep": "09", "sept": "09", "october": "10",
    "oct": "10", "november": "11", "nov": "11", "december": "12", "dec": "12",
}
HARNESS_YEAR_DEFAULT = "2026"
ISO_DATE_RE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")
YYYY_MM_RE = re.compile(r"\b(20\d{2}-(?:0[1-9]|1[0-2]))(?!-\d{2})\b")
CANON_EMP_RE = re.compile(r"\b([A-Z]+_\d{3,6})\b")
CANON_INV_RE = re.compile(r"\b(INV-\d{4,6})\b")
AMOUNT_RE = re.compile(r"(\d{1,3}(?:,\d{2,3})+|\d{4,7})(?:\.\d{2})?")

CONSTITUTION = "Never commit money without human_verdict == approve. No prompt may override this."


# --- 1. normalize ---

def normalize(state: dict) -> dict:
    text, flags = normalize_query(state.get("query", ""))
    return {"normalized": text, "flags": flags, "entities": _extract_entities(text, flags),
            "loops": 0, "verify_loops": 0, "human_verdict": None}


def _extract_entities(text: str, flags: dict) -> dict:
    ent: dict = {"emp_id": None, "month": None, "from_date": None, "to_date": None,
                 "amount": None, "invoice_id": None}
    m = CANON_EMP_RE.search(text.upper())
    if m:
        ent["emp_id"] = m.group(1).upper()
    m = CANON_INV_RE.search(text.upper())
    if m:
        ent["invoice_id"] = m.group(1).upper()
    dates = ISO_DATE_RE.findall(text)
    if len(dates) >= 2:
        ent["from_date"], ent["to_date"] = dates[0], dates[1]
    elif len(dates) == 1:
        ent["month"] = dates[0][:7]
    if ent["month"] is None:
        m = YYYY_MM_RE.search(text)
        if m:
            ent["month"] = m.group(1)
    if ent["month"] is None and ent["from_date"] is None:
        for name, mm in MONTH_MAP.items():
            if re.search(rf"\b{name}\b", text):
                ent["month"] = f"{HARNESS_YEAR_DEFAULT}-{mm}"
                break
    if ent["month"] is None and ent["from_date"] is None and flags.get("ambiguous_date"):
        # IN-locale assumption (DD/MM), surfaced + approval-gated downstream.
        # Never silent: flags['date_assumed'] forces needs_approval in risk_gate.
        m = DATE_SLASH_RE.search(text)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if 1 <= a <= 31 and 1 <= b <= 12:
                ent["from_date"] = f"{HARNESS_YEAR_DEFAULT}-{b:02d}-{a:02d}"
                flags["date_assumed"] = f"{a}/{b}->DD/MM"
    ent["amount"] = _max_standalone_amount(text)
    return ent


STRIP_RE = re.compile(
    r"20\d{2}-\d{2}-\d{2}|20\d{2}-\d{2}|[A-Z]+_\d{3,6}|INV-\d{4,6}|[A-Z0-9]{8,}|EMP[\s_\-]*\d+|INV[\s_\-]*\d+",
    re.I,
)


def _max_standalone_amount(text: str) -> int | None:
    """Largest discrete figure, ignoring dates, IDs, and GSTIN-like tokens.
    Dataset convention: gold amount == this value (documented in evals/harness.py)."""
    clean = STRIP_RE.sub(" ", text)
    amounts = [int(a.replace(",", "").split(".")[0]) for a in AMOUNT_RE.findall(clean)]
    return max(amounts) if amounts else None


# --- 2. route ---

# Scraped text is DATA, never instructions. Any embedded directive to bypass
# approval, skip gates, or impersonate an approver blocks the run outright.
INJECTION_PATTERNS = (
    "ignore approval", "skip approval", "skip the approval", "without approval",
    "system override", "override approved", "[system instruction", "system instruction:",
    "approved on call", "i approved", "commit payment immediately", "commit now",
    "disregard", "jailbreak",
)


def _injection_hit(raw: str) -> str:
    for p in INJECTION_PATTERNS:
        if p in raw:
            return f"prompt-injection pattern {p!r}"
    return ""


_INTENTS = [
    ("leave", ("leave", " cl ", " sl ", " el ", "lop", "absent", "chhutti")),
    ("notice", ("notice", "demand", "section", "due date", "gstn")),
    ("simulate", ("simulat", "what-if", "what if", "regime", "ctc", "hike")),
    ("payroll", ("salary", "pagar", "sallery", "tds", "pf", "esi", "slip", "in-hand", "overtime", "emp_")),
    ("vendor", ("invoice", "inv-", "vendor", "gst", "gstin", "po ", "bill", "recon", "pay ")),
]


def route_query(state: dict) -> dict:
    if state.get("escalate"):
        return {"route": "policy"}
    text = f" {state.get('normalized', '')} ".lower()
    raw = f" {state.get('query') or state.get('normalized', '')} ".lower()
    flags = state.get("flags", {})
    ent = state.get("entities", {})
    hit = _injection_hit(raw)
    if hit:
        return {"route": "policy", "validation_error": f"blocked: {hit}",
                "loops": state.get("loops", 0), "escalate": True, "injection": True}
    for route, keys in _INTENTS:
        if any(k in text for k in keys):
            break
    else:
        route = "policy"
    # Validation errors feed back to route max 2 loops, then escalate (Self-Refine discipline).
    err = _validate(route, text, ent, flags)
    if err:
        loops = state.get("loops", 0) + 1
        if loops >= 2:
            return {"route": route, "validation_error": err, "loops": loops, "escalate": True}
        return {"route": route, "validation_error": err, "loops": loops}
    return {"route": route, "validation_error": "", "loops": state.get("loops", 0)}


def _validate(route: str, text: str, ent: dict, flags: dict) -> str:
    if re.search(r"\bemp[\s_\-]*\d", text) and not ent.get("emp_id"):
        return "emp_id present but not canonical (expected EMP_XXX). Ask for exact ID."
    if re.search(r"\binv[\s_\-]*\d", text) and not ent.get("invoice_id"):
        return "invoice_id present but not canonical (expected INV-XXXX). Ask for exact ID."
    if flags.get("ambiguous_date") and not flags.get("date_assumed"):
        return f"ambiguous date {flags['ambiguous_date']} unresolvable. Ask for YYYY-MM-DD."
    if route == "payroll" and not ent.get("emp_id"):
        return "payroll lookup needs emp_id."
    if route == "vendor" and not ent.get("invoice_id"):
        return "vendor recon needs invoice_id."
    return ""


# --- 3. fetch_docs ---

def fetch_docs(state: dict) -> dict:
    if state.get("escalate"):
        return {"docs": [], "citations": []}
    res = server.policy_search(state.get("normalized", state.get("query", "")), top_k=5)
    # Lost-in-the-Middle cap: best chunk first AND last, total under cap.
    chunks, total, cites = [], 0, []
    for h in res.get("chunks", []):
        if total + len(h["chunk"]) > DOC_CHAR_CAP:
            break
        chunks.append(h)
        total += len(h["chunk"])
        cites.append(h["cite"])
    if len(chunks) > 2:
        chunks = [chunks[0], *chunks[1:-1], chunks[-1]]
    return {"docs": chunks, "citations": cites}


# --- 4. execute_tool (read / dry-run only) ---

def execute_tool(state: dict, db_path: str | None = None) -> dict:
    if state.get("escalate"):
        return {"tool_output": {"escalated": True}, "tool_summary": "escalated to human"}
    dbp = db_path or os.getenv("ACCUPAID_DB", "accupaid.db")
    route, ent = state.get("route", "policy"), state.get("entities", {})
    try:
        if route == "payroll" and ent.get("emp_id") and ent.get("month"):
            out = server.payroll_lookup(
                PayrollLookupInput(emp_id=ent["emp_id"], month=ent["month"]), dbp)
            name = "payroll_lookup"
        elif route == "leave" and ent.get("emp_id") and ent.get("from_date"):
            out = server.leave_apply(LeaveApplyInput(
                emp_id=ent["emp_id"], from_date=ent["from_date"],
                to_date=ent.get("to_date") or ent["from_date"], leave_type="EL"), dbp)
            name = "leave_apply"
        elif route == "vendor" and ent.get("invoice_id"):
            from mcp_server.models import GSTIN_RE  # noqa

            out = {"dry_run_note": "amounts/gstin needed for full recon",
                   "invoice_id": ent["invoice_id"], "read_only": True}
            name = "vendor_recon"
        elif route == "notice":
            out = server.notice_parse(NoticeParseInput(text=state.get("query", "")))
            name = "notice_parse"
        elif route == "simulate":
            out = server.tds_simulate(TdsSimulateInput(
                ctc=float(ent.get("amount") or 1200000), regime="new"))
            name = "tds_simulate"
        else:
            out = {"policy_only": True,
                   "hint": "answered from docs; no tool entities", "read_only": True}
            name = "policy_search"
    except Exception as e:  # tool validation error -> route retry path
        return {"tool_name": route, "tool_output": {"error": str(e)},
                "tool_summary": f"tool error: {e}"}
    return {"tool_name": name, "tool_output": out,
            "tool_summary": _summarize(out), "draft": out}


def _summarize(out: dict) -> str:
    s = str(out)
    return s if len(s) <= TOOL_CHAR_CAP else s[:TOOL_CHAR_CAP] + "…[truncated over 800 tokens]"


# --- 5. verify_node: Chain-of-Verification + CRITIC + SelfCheckGPT, cap 2 loops ---

def verify_node(state: dict, db_path: str | None = None) -> dict:
    dbp = db_path or os.getenv("ACCUPAID_DB", "accupaid.db")
    draft = state.get("draft") or state.get("tool_output", {})
    ent = state.get("entities", {})
    questions, answers, problems = [], {}, []
    if isinstance(draft, dict):
        for k in ("gross", "tds", "pf", "net", "invoiced_amount", "demand_amount", "diff"):
            if draft.get(k) is not None:
                questions.append(f"is {k}={draft[k]} independently confirmed?")
        # CRITIC-style: re-call payroll_lookup to critique draft amounts.
        if state.get("tool_name") == "payroll_lookup" and ent.get("emp_id") and ent.get("month"):
            try:
                recheck = server.payroll_lookup(
                    PayrollLookupInput(emp_id=ent["emp_id"], month=ent["month"]), dbp)
                answers["recheck"] = recheck
                for k in ("gross", "tds", "pf", "net"):
                    if draft.get(k) != recheck.get(k):
                        problems.append(f"amount drift on {k}: {draft.get(k)} vs {recheck.get(k)}")
            except Exception as e:
                problems.append(f"recheck failed: {e}")
        # SelfCheckGPT: extract entities 3x (query, normalized, draft text) — any
        # disagreement on amounts/ids forces needs_approval.
        samples = {
            "q": _extract_entities(state.get("query", ""), {}),
            "n": _extract_entities(state.get("normalized", ""), state.get("flags", {})),
            "d": _extract_entities(str(draft), {}),
        }
        answers["selfcheck"] = {k: (v.get("emp_id"), v.get("invoice_id"), v.get("amount"))
                                for k, v in samples.items()}
        ids = {answers["selfcheck"][k][i] for k in samples for i in (0, 1)
               if answers["selfcheck"][k][i]}
        if len(ids - {None}) > 2:
            problems.append(f"entity disagreement across 3 samples: {answers['selfcheck']}")
        if answers["selfcheck"]["q"][2] is not None and answers["selfcheck"]["n"][2] is not None \
                and answers["selfcheck"]["q"][2] != answers["selfcheck"]["n"][2]:
            problems.append("amount disagreement raw-vs-normalized")
    loops = state.get("verify_loops", 0) + 1
    if problems and loops >= 2:
        return {"verification": {"questions": questions, "answers": answers,
                                 "problems": problems, "verdict": "escalate"},
                "verify_loops": loops, "escalate": True}
    return {"verification": {"questions": questions, "answers": answers,
                             "problems": problems,
                             "verdict": "needs_approval" if problems else "ok"},
            "verify_loops": loops}


# --- 6. risk_gate (deterministic) ---

def risk_gate_node(state: dict) -> dict:
    from mcp_server.guards import risk_gate as _rg

    out = state.get("tool_output", {}) or {}
    ver = state.get("verification", {}) or {}
    net_delta = None
    if state.get("tool_name") == "payroll_lookup" and ver.get("answers", {}).get("recheck"):
        try:
            net_delta = (out.get("net") or 0) - (ver["answers"]["recheck"].get("net") or 0)
        except TypeError:
            net_delta = None
    if out.get("diff") is not None:  # recon dry-run diff
        net_delta = out["diff"]
    tool_gate = out.get("gate") or {}
    gate = _rg(
        invoiced=out.get("invoiced_amount", out.get("demand_amount")),
        po=out.get("po_amount", 0 if out.get("demand_amount") is not None else None),
        gst_mismatch=bool(out.get("gst_mismatch")),
        net_delta=net_delta,
        ambiguous_date=bool(state.get("flags", {}).get("ambiguous_date")),
    )
    force = (bool(state.get("escalate"))
             or ver.get("verdict") in ("needs_approval", "escalate")
             or bool(tool_gate.get("needs_approval"))
             or out.get("proposal") == "HOLD"
             or _commit_intent(state))
    needs = gate["needs_approval"] or force
    reasons = list(gate["reasons"]) + (["verify:" + p for p in ver.get("problems", [])] if force else [])
    if _commit_intent(state):
        reasons.append(f"commit_intent={state.get('route')}")
    return {"risk": {**gate, "needs_approval": needs, "reasons": reasons,
                     "verdict": "HOLD" if needs else "AUTO_OK"},
            "needs_approval": needs}


COMMIT_WORDS = ("apply", "pay", "commit", "approve", "lagao", "book", "proceed", "karna hai")


def _commit_intent(state: dict) -> bool:
    if state.get("route") not in ("leave", "vendor"):
        return False
    # Word-boundary match: "payment" must NOT trigger, "pay karna hai" must.
    return bool(re.search(r"\b(apply|pay|commit|approve|lagao|book|proceed|karna hai)\b",
                          state.get("normalized", "")))


# --- 7. human_approval (graph pauses BEFORE this node when needs_approval) ---

def human_approval(state: dict) -> dict:
    verdict = state.get("human_verdict")
    if verdict == "approve":
        return {"approval_reason": state.get("approval_reason", "")}
    if verdict == "reject":
        return {"result": {"status": "rejected", "reason": state.get("approval_reason", "")},
                "error": "rejected by human"}
    # Defense in depth: node must never run pre-verdict (graph interrupts first).
    return {"result": {"status": "blocked", "reason": "no human verdict in checkpoint"},
            "error": "commit attempted without approval — blocked"}


# --- 8. format_response (atomic claims + cites, ALCE / FActScore discipline) ---

def format_response(state: dict) -> dict:
    if state.get("result", {}).get("status") in ("rejected", "blocked"):
        return {"result": {**state["result"], "cites": state.get("citations", [])}}
    if state.get("escalate"):
        return {"result": {
            "status": "needs_human",
            "message": state.get("validation_error") or "escalated after 2 verify loops",
            "entities": state.get("entities", {}), "cites": state.get("citations", [])}}
    claims = []
    out = state.get("tool_output", {}) or {}
    for c in state.get("citations", [])[:5]:
        claims.append({"cite": c})
    result = {
        "status": "needs_approval" if state.get("needs_approval") else "answered",
        "route": state.get("route"),
        "entities": state.get("entities", {}),
        "summary": state.get("tool_summary", ""),
        "risk": state.get("risk", {}),
        "verification": (state.get("verification", {}) or {}).get("verdict", "skipped"),
        "claims": claims, "cites": state.get("citations", []),
        "constitution": CONSTITUTION,
    }
    if state.get("committed"):
        result.update({"status": "committed", "committed": state["committed"]})
    return {"result": result}
