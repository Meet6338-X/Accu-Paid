"""PR6 gates: policy corpus recall on Hinglish queries + ingest chunk contract."""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp_server import server
from rag.ingest import chunk_text, ingest


def test_ingest_builds_index(tmp_path):
    out = str(tmp_path / "index.jsonl")
    stats = ingest("rag/policy_docs", out)
    assert stats["docs"] == 7
    assert stats["chunks"] >= 7
    rows = [json.loads(line) for line in open(out, encoding="utf-8")]
    assert all({"doc_id", "cite", "text"} <= set(r) for r in rows)


def test_chunk_overlap_keeps_context():
    chunks = chunk_text("word " * 2000, size=400, overlap=100)
    assert len(chunks) > 1
    assert chunks[0][-50:] in chunks[1]  # overlap carried


def test_tds_recall_hinglish():
    out = server.policy_search("mera march ki salary kam ayi, TDS jyada kata?")
    cites = " ".join(h["cite"] for h in out["chunks"])
    assert "tds" in cites or "glossary" in cites


def test_gst_recall_codemixed():
    out = server.policy_search("GST me mismatch hai invoice ka?")
    assert any(h["doc_id"] in ("gst", "gst-mismatch-2026") for h in out["chunks"])


def test_lop_recall():
    out = server.policy_search("salary kam ayi absent LOP days?")
    assert any(h["doc_id"] in ("lop", "lop-2026") for h in out["chunks"])


def test_every_answer_can_cite():
    out = server.policy_search("overtime missing pay")
    assert out["chunks"], "no chunk for overtime query"
    assert all(h["cite"].startswith("[") for h in out["chunks"])
