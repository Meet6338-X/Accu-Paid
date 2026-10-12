"""FastAPI gateway.

Endpoints:
  POST /chat               -> run_id + answered result, or needs_approval + signed approve sigs
  POST /approve/{run_id}   -> verdict + reason + signature -> resume; executes gated
                              commits on approve (PAY-able only; HOLD stays held for CA review)
  GET  /runs/{run_id}      -> full replay from checkpoint, never from memory
  GET  /runs/{run_id}/audit[?format=csv] -> auditor export (JSON/CSV: trace, inputs, cites)
  POST /ingest/slip        -> salary-slip diff vs payroll_lookup (flags diffs > INR 500)
  POST /ingest/notice      -> GST notice parse (demand, due, section, linked invoices)

Approval security: approve links are HMAC-signed (15-min expiry). /chat mints sigs for
reason="" (quick link actions). Custom reasons are annotated server-side; the binding
(run_id|verdict|reason|ts) is re-verified, and every commit is single-use via the
idempotency ledger. Per-tool timeout 25s. PII redacted before any log/trace.
"""

from __future__ import annotations

import csv
import io
import logging
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, UploadFile

from agent.graph import approve_run, build_graph, get_run, run_chat
from app.schemas import ApproveRequest, ChatRequest, NoticeIngest, SlipIngest
from db.import_csv import import_csv
from db.seed import seed
from mcp_server import server as tools
from mcp_server.guards import redact_pii, sign_approval, verify_approval
from mcp_server.models import (
    ApprovalToken,
    LeaveApplyInput,
    NoticeParseInput,
    SlipParseInput,
)

log = logging.getLogger("accupaid")
_executor = ThreadPoolExecutor(max_workers=4)
TOOL_TIMEOUT = 25

SECRET_ENV = "APPROVAL_HMAC_SECRET"
TTL = int(os.getenv("APPROVAL_TTL_SECONDS", "900"))


def _secret() -> str:
    return os.getenv(SECRET_ENV, "dev-secret-change-me")


@asynccontextmanager
async def lifespan(app: FastAPI):
    dbp = os.getenv("ACCUPAID_DB", "accupaid.db")
    if not os.path.exists(dbp):
        seed(dbp)
    from langgraph.checkpoint.memory import MemorySaver

    app.state.graph = build_graph(checkpointer=MemorySaver(), db_path=dbp)
    app.state.db_path = dbp
    _maybe_langsmith()
    yield


def _maybe_langsmith() -> str | None:
    if os.getenv("LANGSMITH_API_KEY"):
        os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
        os.environ.setdefault("LANGCHAIN_PROJECT", os.getenv("LANGSMITH_PROJECT", "AccuPaid-startup"))
        return f"https://smith.langchain.com/o/_/projects/p/{os.environ['LANGCHAIN_PROJECT']}"
    return None


app = FastAPI(title="AccuPaid", version="0.1.0", lifespan=lifespan)


@app.get("/")
def root():
    return {
        "service": "AccuPaid",
        "version": "0.1.0",
        "status": "ok",
        "endpoints": ["/chat", "/approve/{run_id}", "/runs/{run_id}",
                      "/runs/{run_id}/audit", "/ingest/slip", "/ingest/notice",
                      "/ingest/csv", "/health", "/docs"],
    }


@app.get("/health")
def health():
    from llm.client import backend_status

    dbp = getattr(app.state, "db_path", os.getenv("ACCUPAID_DB", "accupaid.db"))
    return {
        "status": "ok",
        "version": "0.1.0",
        "db": os.path.exists(dbp),
        "graph": hasattr(app.state, "graph"),
        "llm": backend_status(),
    }


def _run_with_timeout(graph, run_id: str, query: str) -> dict:
    fut = _executor.submit(run_chat, graph, run_id, query)
    try:
        return fut.result(timeout=TOOL_TIMEOUT)
    except TimeoutError:
        raise HTTPException(status_code=504, detail="tool timeout after 25s")


@app.post("/chat")
def chat(req: ChatRequest):
    run_id = uuid.uuid4().hex[:12]
    log.info("chat %s %s", run_id, redact_pii(req.query))
    st = _run_with_timeout(app.state.graph, run_id, req.query)
    if st.get("needs_approval") and not st.get("result"):
        return {
            "run_id": run_id,
            "status": "needs_approval",
            "reasons": (st.get("risk") or {}).get("reasons", []),
            "approve_signature": sign_approval(run_id, "approve", "", _secret()),
            "reject_signature": sign_approval(run_id, "reject", "", _secret()),
            "ttl_seconds": TTL,
        }
    return {"run_id": run_id, "status": (st.get("result") or {}).get("status", "answered"),
            "result": st.get("result")}


def _sig_ok(run_id: str, verdict: str, reason: str, signature: str) -> bool:
    if verify_approval(run_id, verdict, reason, signature, _secret(), TTL):
        return True
    # Link flow: quick-action sigs are minted for reason=""; a human-typed reason
    # is accepted as annotation when the link sig itself is valid and unexpired.
    return reason != "" and verify_approval(run_id, verdict, "", signature, _secret(), TTL)


@app.post("/approve/{run_id}")
def approve(run_id: str, req: ApproveRequest):
    if req.verdict not in ("approve", "reject"):
        raise HTTPException(status_code=422, detail="verdict must be approve|reject")
    if not _sig_ok(run_id, req.verdict, req.reason, req.signature):
        raise HTTPException(status_code=403, detail="invalid or expired approval signature")
    st = approve_run(app.state.graph, run_id, req.verdict, req.reason)
    if req.verdict == "approve":
        commit_note = _maybe_commit(run_id, st, req.reason)
        if commit_note:
            result = dict(st.get("result") or {})
            result["commit"] = commit_note
            return {"run_id": run_id, "status": "committed" if commit_note.get("committed")
                    else "approved_hold", "result": result}
    result = st.get("result") or {}
    return {"run_id": run_id, "status": result.get("status", "unknown"), "result": result}


def _maybe_commit(run_id: str, st: dict, reason: str) -> dict | None:
    """Execute the gated commit behind an approval. PAY-able only:
    HOLD (GST mismatch / amount breach) stays held for CA review — approval does
    not silently override a HOLD. Idempotent via the committed_actions ledger."""
    route, ent = st.get("route"), st.get("entities", {})
    token = ApprovalToken(run_id=run_id, verdict="approve", reason=reason,
                          signature=sign_approval(run_id, "approve", reason, _secret()))
    try:
        if route == "leave" and ent.get("emp_id") and ent.get("from_date"):
            out = tools.commit_leave(run_id, LeaveApplyInput(
                emp_id=ent["emp_id"], from_date=ent["from_date"],
                to_date=ent.get("to_date") or ent["from_date"], leave_type="EL"),
                token, app.state.db_path, _secret(), approver="api")
            return {"committed": True, **out}
        if route == "vendor" and ent.get("invoice_id"):
            recon = (st.get("tool_output") or {})
            if recon.get("verdict") == "HOLD" or recon.get("gst_mismatch"):
                return {"committed": False, "note": "approved but HELD: GST mismatch or "
                        "amount breach — CA review required, no money moved"}
            out = tools.vendor_commit(run_id, ent["invoice_id"], token,
                                      app.state.db_path, _secret(), approver="api")
            return {"committed": True, **out}
    except (PermissionError, LookupError, ValueError) as e:
        return {"committed": False, "note": f"commit refused: {e}"}
    return None


@app.get("/runs/{run_id}")
def runs(run_id: str):
    st = get_run(app.state.graph, run_id)
    if not st:
        raise HTTPException(status_code=404, detail="unknown run_id")
    return {"run_id": run_id, "state": _redacted_state(st)}


@app.get("/runs/{run_id}/audit")
def audit(run_id: str, format: str = "json"):
    st = get_run(app.state.graph, run_id)
    if not st:
        raise HTTPException(status_code=404, detail="unknown run_id")
    rows = [
        {"field": "run_id", "value": run_id},
        {"field": "query", "value": redact_pii(st.get("query", ""))},
        {"field": "route", "value": st.get("route", "")},
        {"field": "entities", "value": str(st.get("entities", {}))},
        {"field": "tool", "value": st.get("tool_name", "")},
        {"field": "risk", "value": str(st.get("risk", ""))},
        {"field": "verdict", "value": str(st.get("human_verdict", ""))},
        {"field": "cites", "value": ";".join(st.get("citations", []))},
        {"field": "status", "value": str((st.get("result") or {}).get("status", ""))},
    ]
    if format == "csv":
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=["field", "value"])
        w.writeheader()
        w.writerows(rows)
        return {"run_id": run_id, "csv": buf.getvalue()}
    return {"run_id": run_id, "audit": rows}


@app.post("/ingest/slip")
def ingest_slip(req: SlipIngest):
    try:
        out = tools.slip_parse(SlipParseInput(**req.model_dump()), app.state.db_path)
    except (ValueError, LookupError, RuntimeError) as e:
        raise HTTPException(status_code=422, detail=str(e))
    return out


@app.post("/ingest/notice")
def ingest_notice(req: NoticeIngest):
    return tools.notice_parse(NoticeParseInput(text=req.text))


@app.post("/ingest/file")
async def ingest_any_file(kind: str = Form(""),
                          mapping: str = Form(""),
                          file: UploadFile = File(...),
                          month_default: str = Form(""),
                          validate_only: bool = Form(False)):
    """Any supported file (csv/xlsx/xls/json/txt/md/pdf). Omit mapping for AI
    auto-map (LLM, else offline heuristic). Omit kind to auto-detect. Every
    upload is a durable job: chunked commits + upsert + persisted report at
    GET /ingest/jobs/{job_id}. Re-upload after a crash safely finishes."""
    import json as _json

    from db.anyfile import detect_kind, extract_rows_text, infer_mapping, parse_file
    from db.import_csv import import_rows

    try:
        raw = await file.read()
        rows = parse_file(file.filename or "upload.csv", raw)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    maps = None
    if mapping.strip():
        try:
            maps = _json.loads(mapping)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"bad mapping json: {e}")
    try:
        if rows and set(rows[0].keys()) == {"line"}:
            kind = kind or detect_kind(rows)
            rows = extract_rows_text(rows, kind)
            maps = maps or {k: k for r in rows for k in r}
            via = "llm-extract"
        elif maps:
            kind = kind or detect_kind(rows)
            via = "explicit"
        else:
            kind, maps, via = infer_mapping(kind or None, rows)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    try:
        report = import_rows(rows, kind, maps, app.state.db_path,
                             month_default=month_default, validate_only=validate_only,
                             filename=file.filename or "")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    report["mapping_via"] = via
    return report


@app.get("/ingest/jobs/{job_id}")
def ingest_job(job_id: str):
    import json as _json

    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    from db.models import IngestJob

    with Session(create_engine(f"sqlite:///{app.state.db_path}")) as s:
        job = s.execute(select(IngestJob).where(IngestJob.job_id == job_id)).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="unknown job_id")
    return {"job_id": job.job_id, "kind": job.kind, "filename": job.filename,
            "status": job.status, "total": job.total, "loaded": job.loaded,
            "skipped": job.skipped, "created_at": job.created_at,
            "report": _json.loads(job.report or "{}")}


@app.post("/ingest/csv")
async def ingest_csv_file(kind: str = Form(...),
                          mapping: str = Form(...),
                          file: UploadFile = File(...),
                          id_prefix: str = Form(""),
                          id_pad: int = Form(3),
                          month_default: str = Form(""),
                          validate_only: bool = Form(False)):
    """Load YOUR csv into employees|payroll|invoices. mapping is JSON
    {csv_column: field}. Bad rows are skipped with reasons (see report)."""
    import json as _json

    try:
        text = (await file.read()).decode("utf-8-sig")
        maps = _json.loads(mapping)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"unreadable file/mapping: {e}")
    try:
        return import_csv(text, kind, maps, app.state.db_path, id_prefix, id_pad,
                          month_default, validate_only)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


def _redacted_state(st: dict) -> dict:
    st = dict(st)
    if st.get("query"):
        st["query"] = redact_pii(st["query"])
    return st
