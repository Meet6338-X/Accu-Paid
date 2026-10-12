"""Temporal activities — thin async wrappers over workflows/core.py + db/.

Retry policy: 3 attempts, exponential backoff, non-retryable ValueErrors
(validation problems must fail fast, not 3x).
"""

from __future__ import annotations

import asyncio

from temporalio import activity

from workflows import core

# JSON-safe step I/O only (Temporal payloads must serialize).


@activity.defn
async def parse_file_act(inp: dict) -> dict:
    data = core.read_staged(inp["file_sha"])
    rows = await asyncio.to_thread(core.parse_step, inp["filename"], data)
    return {"n": len(rows), "sample_cols": sorted(rows[0].keys())}


@activity.defn
async def map_act(inp: dict) -> dict:
    from db.anyfile import parse_file

    data = core.read_staged(inp["file_sha"])
    rows = await asyncio.to_thread(parse_file, inp["filename"], data)
    kind, mapping, via, rows = await asyncio.to_thread(core.map_step, inp.get("kind") or "",
                                                       inp.get("mapping"), rows)
    return {"kind": kind, "mapping": mapping, "via": via, "n": len(rows)}


@activity.defn
async def load_act(inp: dict) -> dict:
    """Chunked load with heartbeats. Crash-safe: finished chunks survive in
    SQLite and re-upload upserts the rest (see IngestJob ledger)."""
    from db.anyfile import parse_file
    from db.import_csv import import_rows

    data = core.read_staged(inp["file_sha"])
    rows = await asyncio.to_thread(parse_file, inp["filename"], data)
    kind, mapping, via, rows = await asyncio.to_thread(
        core.map_step, inp.get("kind") or "", inp.get("mapping"), rows)

    def beat(done: int, total: int, stage: str):
        try:
            activity.heartbeat({"done": done, "total": total, "stage": stage})
        except Exception:
            pass  # inline/test context: no activity environment

    report = await asyncio.to_thread(
        import_rows, rows, kind, mapping, inp["db_path"], inp.get("id_prefix", ""),
        inp.get("id_pad", 3), inp.get("month_default", ""), inp.get("validate_only", False),
        inp["job_id"], inp.get("filename", ""), 200, inp["file_sha"],
        inp.get("pii_mode", "report"), beat)
    report["mapping_via"] = via
    return report
