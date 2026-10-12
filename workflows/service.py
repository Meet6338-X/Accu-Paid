"""Ingest service — Temporal when reachable, identical inline fallback otherwise.

Content-addressed jobs: job_id = sha256(file)[:12]. Re-uploading the same
bytes returns the existing report without reprocessing (true dedupe).
Big files (>INLINE_ROWS) go to the server asynchronously (202 + poll);
small files run inline and return the full report (existing tests unchanged).
"""

from __future__ import annotations

import asyncio
import json
import os

TASK_QUEUE = os.getenv("TEMPORAL_TASK_QUEUE", "accupaid-ingest")
INLINE_ROWS = int(os.getenv("ACCUPAID_INLINE_ROWS", "500"))

_client = None


async def get_client():
    """Short-timeout connect; None when the server is absent (fallback path)."""
    global _client
    if _client is not None:
        return _client
    if os.getenv("TEMPORAL_DISABLED") == "1":
        return None
    try:
        from temporalio.client import Client

        _client = await Client.connect(os.getenv("TEMPORAL_HOST", "localhost:7233"),
                                       namespace=os.getenv("TEMPORAL_NAMESPACE", "default"))
        return _client
    except Exception:
        return None


def reset_client():
    global _client
    _client = None


def ledger_report(db_path: str, job_id: str) -> dict | None:
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    from db.models import IngestJob

    if not os.path.exists(db_path):
        return None
    with Session(create_engine(f"sqlite:///{db_path}")) as s:
        job = s.execute(select(IngestJob).where(IngestJob.job_id == job_id)).scalar_one_or_none()
    if job is None:
        return None
    rep = json.loads(job.report or "{}")
    rep.update({"job_id": job.job_id, "status": job.status, "mode": job.mode,
                "progress": job.progress, "stage": job.stage})
    return rep


async def submit(filename: str, data: bytes, kind: str, mapping: dict | None,
                 db_path: str, month_default: str = "", validate_only: bool = False,
                 pii_mode: str = "report", wait: bool = True) -> tuple[int, dict]:
    """Returns (http_status, body). 200 full report | 202 running | 422 bad input."""
    from workflows import core
    from workflows.ingest import IngestInput, run_inline

    try:
        core.check_caps(filename, data)
    except ValueError as e:
        return 422, {"detail": str(e)}
    sha = core.file_sha(data)
    job_id = sha[:12]
    seen = ledger_report(db_path, job_id)
    if seen and seen.get("status") in ("DONE", "DRYRUN"):
        seen["deduped_upload"] = True
        return 200, seen
    core.stage_file(sha, data)
    inp = IngestInput(job_id=job_id, file_sha=sha, filename=filename, kind=kind or "",
                      mapping=mapping or {}, db_path=db_path, month_default=month_default,
                      validate_only=validate_only, pii_mode=pii_mode)
    client = await get_client()
    use_temporal = client is not None and not validate_only
    if use_temporal:
        try:
            from workflows.ingest import IngestFileWorkflow

            wid = f"ingest-{sha[:16]}"
            handle = await client.start_workflow(
                IngestFileWorkflow.run, inp, id=wid, task_queue=TASK_QUEUE)
            if wait:
                try:
                    report = await asyncio.wait_for(handle.result(), timeout=120)
                    _finalize_ledger(db_path, job_id, report)
                    return 200, report
                except asyncio.TimeoutError:
                    pass
                except Exception as e:
                    # Fast failure (bad mapping/validation) — don't strand as RUNNING.
                    _mark(db_path, job_id, kind, filename, sha, "temporal",
                          failed=str(e), extra={"workflow_id": wid})
                    return 422, {"detail": str(e)}
            _mark(db_path, job_id, kind, filename, sha, "temporal",
                  extra={"workflow_id": wid})
            return 202, {"job_id": job_id, "status": "RUNNING", "mode": "temporal",
                         "workflow_id": wid}
        except Exception:
            pass  # server died mid-submit -> inline fallback below
    try:
        report = await asyncio.to_thread(run_inline, inp)
    except ValueError as e:
        _mark(db_path, job_id, kind, filename, sha, "inline", failed=str(e))
        return 422, {"detail": str(e)}
    return 200, report


def _finalize_ledger(db_path: str, job_id: str, report: dict) -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from db.models import Base, IngestJob

    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        s.merge(IngestJob(job_id=job_id, kind=report.get("kind", ""),
                          filename=(report.get("filename") or "")[:256], status="DONE",
                          total=report.get("total", 0), loaded=report.get("loaded", 0),
                          skipped=report.get("skipped", 0),
                          report=json.dumps(report, default=str)[:20000],
                          file_sha="", progress=100, stage="done", mode="temporal"))
        s.commit()


def _mark(db_path, job_id, kind, filename, sha, mode, failed="", extra=None):
    import time as _time

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from db.models import Base, IngestJob

    body = dict(extra or {})
    if failed:
        body["error"] = failed

    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        s.merge(IngestJob(job_id=job_id, kind=kind, filename=filename[:256],
                          status="FAILED" if failed else "RUNNING",
                          report=json.dumps(body)[:20000],
                          created_at=_time.strftime("%Y-%m-%dT%H:%M:%S"),
                          file_sha=sha, progress=0, stage="queued", mode=mode))
        s.commit()


async def _handle_for(rep: dict):
    from workflows.ingest import IngestFileWorkflow

    client = await get_client()
    if client is None:
        return None
    wid = rep.get("workflow_id")
    if not wid:
        return None
    return client.get_workflow_handle_for(IngestFileWorkflow.run, wid)


async def progress(db_path: str, job_id: str) -> dict | None:
    rep = ledger_report(db_path, job_id)
    if rep is None:
        return None
    if rep.get("status") != "RUNNING":
        return rep
    try:
        handle = await _handle_for(rep)
        if handle is None:
            return rep
        try:
            desc = await handle.describe()
            st = str(desc.status)
            if "FAILED" in st or "TERMINATED" in st or "CANCELLED" in st:
                _set_status(db_path, job_id, st.split(".")[-1])
                rep["status"] = st.split(".")[-1]
                return rep
        except Exception:
            pass
        q = await handle.query("progress")
        rep.update({"progress": int(100 * q["done"] / max(q["total"], 1)),
                    "stage": q["stage"]})
    except Exception:
        pass
    return rep


def _set_status(db_path: str, job_id: str, status: str) -> None:
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    from db.models import IngestJob

    with Session(create_engine(f"sqlite:///{db_path}")) as s:
        job = s.execute(select(IngestJob).where(IngestJob.job_id == job_id)).scalar_one_or_none()
        if job is not None:
            job.status = status
            s.commit()


async def cancel(db_path: str, job_id: str) -> tuple[int, dict]:
    rep = ledger_report(db_path, job_id)
    if rep is None:
        return 404, {"detail": "unknown job_id"}
    if rep.get("status") != "RUNNING":
        return 409, {"detail": f"job already {rep.get('status')}"}
    try:
        handle = await _handle_for(rep)
        if handle is None:
            return 409, {"detail": "job not running on a reachable server"}
        await handle.cancel()
        return 200, {"job_id": job_id, "status": "CANCELLED"}
    except Exception as e:
        return 409, {"detail": f"cancel failed: {e}"}
