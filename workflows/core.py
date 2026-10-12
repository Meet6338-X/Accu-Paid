"""Shared ingest steps — used by BOTH the Temporal activities and the inline path.

Parity rule: activities are thin wrappers over these functions, so fallback
and server runs produce identical reports.
"""

from __future__ import annotations

import hashlib
import os

STAGING_DIR = os.getenv("ACCUPAID_STAGING", "data/staging")
MAX_FILE_MB = int(os.getenv("ACCUPAID_MAX_FILE_MB", "25"))
MAX_ROWS = int(os.getenv("ACCUPAID_MAX_ROWS", "100000"))


def check_caps(filename: str, data: bytes) -> None:
    if len(data) > MAX_FILE_MB * 1024 * 1024:
        raise ValueError(f"file too large ({len(data) // 1048576}MB > {MAX_FILE_MB}MB)")
    if not data:
        raise ValueError("empty file")


def stage_file(file_sha: str, data: bytes) -> str:
    """Spill uploads to local staging so Temporal workers (same-machine
    deployment) read bytes by hash. Multi-node: point ACCUPAID_STAGING at
    shared storage or S3."""
    os.makedirs(STAGING_DIR, exist_ok=True)
    path = os.path.join(STAGING_DIR, f"{file_sha}.bin")
    if not os.path.exists(path):
        with open(path, "wb") as f:
            f.write(data)
    return path


def read_staged(file_sha: str) -> bytes:
    path = os.path.join(STAGING_DIR, f"{file_sha}.bin")
    with open(path, "rb") as f:
        return f.read()


def parse_step(filename: str, data: bytes) -> list[dict]:
    from db.anyfile import parse_file

    rows = parse_file(filename, data)
    if len(rows) > MAX_ROWS:
        raise ValueError(f"too many rows ({len(rows)} > {MAX_ROWS})")
    if not rows:
        raise ValueError("no rows parsed")
    return rows


def map_step(kind: str, mapping: dict | None, rows: list[dict]) -> tuple[str, dict, str]:
    from db.anyfile import detect_kind, extract_rows_text, infer_mapping

    if rows and set(rows[0].keys()) == {"line"}:
        kind = kind or detect_kind(rows)
        rows = extract_rows_text(rows, kind)
        return kind, {k: k for r in rows for k in r}, "llm-extract", rows
    if mapping:
        return kind or detect_kind(rows), mapping, "explicit", rows
    k, m, via = infer_mapping(kind or None, rows)
    return k, m, via, rows


def file_sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
