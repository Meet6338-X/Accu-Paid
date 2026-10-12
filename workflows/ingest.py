"""IngestFileWorkflow — durable file import.

Guarantees (Temporal semantics): at-least-once activity execution with
exponential-backoff retries; heartbeated chunk loader; external cancel;
live progress via the `progress` query. Idempotency comes from the ledger:
content-addressed job_id + natural-key upserts, so replays and re-uploads
converge instead of duplicating.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from workflows import activities


@dataclass
class IngestInput:
    job_id: str
    file_sha: str
    filename: str = ""
    kind: str = ""
    mapping: dict = field(default_factory=dict)
    db_path: str = "accupaid.db"
    id_prefix: str = ""
    id_pad: int = 3
    month_default: str = ""
    validate_only: bool = False
    pii_mode: str = "report"


@workflow.defn
class IngestFileWorkflow:
    def __init__(self) -> None:
        self._progress = {"done": 0, "total": 0, "stage": "parse"}

    @workflow.query
    def progress(self) -> dict:
        return dict(self._progress)

    @workflow.run
    async def run(self, inp: IngestInput) -> dict:
        base = {"job_id": inp.job_id, "file_sha": inp.file_sha, "filename": inp.filename,
                "db_path": inp.db_path, "kind": inp.kind, "mapping": inp.mapping,
                "id_prefix": inp.id_prefix, "id_pad": inp.id_pad,
                "month_default": inp.month_default, "validate_only": inp.validate_only,
                "pii_mode": inp.pii_mode}
        retry = RetryPolicy(
            maximum_attempts=3, initial_interval=timedelta(seconds=2),
            non_retryable_error_types=["ValueError"])
        parsed = await workflow.execute_activity(
            activities.parse_file_act, base, start_to_close_timeout=timedelta(minutes=5),
            retry_policy=retry)
        self._progress = {"done": 0, "total": parsed["n"], "stage": "map"}
        mapped = await workflow.execute_activity(
            activities.map_act, base, start_to_close_timeout=timedelta(minutes=5),
            retry_policy=retry)
        self._progress = {"done": 0, "total": mapped["n"], "stage": "load"}
        report = await workflow.execute_activity(
            activities.load_act, base, start_to_close_timeout=timedelta(hours=1),
            heartbeat_timeout=timedelta(minutes=2), retry_policy=retry)
        self._progress = {"done": mapped["n"], "total": mapped["n"], "stage": "done"}
        report["mode"] = "temporal"
        return report


def run_inline(inp: IngestInput) -> dict:
    """Identical pipeline without a server (fallback + tests). Not a coroutine."""
    import asyncio as _asyncio

    async def go():
        from workflows import activities as _a

        parsed = await _a.parse_file_act(inp.__dict__)
        _ = parsed
        mapped = await _a.map_act(inp.__dict__)
        _ = mapped
        report = await _a.load_act(inp.__dict__)
        report["mode"] = "inline"
        return report

    return _asyncio.run(go())
