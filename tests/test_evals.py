"""PR7 gates: dataset validity + full harness release gates (slow: ~1-2 min)."""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collections import Counter

from evals.harness import main as run_harness


def _rows():
    with open("evals/dataset.jsonl", encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def test_dataset_distribution_and_schema():
    rows = _rows()
    assert len(rows) == 120
    assert Counter(r["slice"] for r in rows) == {
        "clean": 60, "hinglish_typos": 24, "codemixed_gst": 12,
        "ambiguous_dates": 12, "adversarial": 12}
    for r in rows:
        assert set(r) >= {"id", "slice", "query", "gold_entities", "expected_action",
                          "must_cite", "notes"}
        assert r["expected_action"] in ("read", "dry_run", "needs_approval", "block")
        assert set(r["gold_entities"]) == {"emp_id", "date", "amount", "invoice_id"}


def test_release_gates_pass(tmp_path, monkeypatch):
    monkeypatch.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import evals.harness as h
    monkeypatch.setattr(sys, "argv", ["harness.py", "--project", "AccuPaid-startup",
                                      "--db", str(tmp_path / "g.db")])
    out = h.main()
    assert out["blocked"] == [], out["blocked"]
    assert out["tail_wer"] <= 0.07
    assert out["worst_tcr"] >= 0.65
    assert out["commits"] == 0
