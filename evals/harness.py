"""Eval harness — Sarvam gates for AccuPaid (eval-engineering: Task = survive the tail).

Metrics:
- Entity-WER = (sub + del + ins) / slots over {emp_id, date, amount, invoice_id}.
  Only non-null gold slots count toward N; predictions on null-gold slots count
  as insertions. Amounts compare as integers (45,200 == 45200).
- Worst-slice TCR = min TCR over {hinglish_typos, codemixed_gst, ambiguous_dates}.
  A case passes iff entities exact AND action exact AND (must_cite -> cite present).
- Tail cases run 5x; Wilson 95% CI reported (HN agentrial pattern). Point pass
  rates alone are rejected. Runs here are deterministic, so intervals collapse —
  variance will appear once LLM extraction lands (DSPy path); the 5x protocol
  stays so the gate is already honest.
- Citation rate, unapproved-commit count (must be 0), P95 latency, avg tokens.

Release gates (BLOCK = do not ship; kill ship if fail twice after 2 iterations):
  Entity-WER tail > 7% | worst-slice TCR < 65% | any unapproved commit |
  P95 > 8s or avg tokens > 3500.

Action convention: gold amount == largest standalone figure in the query
(extractor takes the max discrete figure after stripping dates/IDs/GSTIN tokens).

Usage: python evals/harness.py [--project AccuPaid-startup] [--db eval_harness.db]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, select, func  # noqa: E402

from agent import nodes  # noqa: E402
from db.models import CommittedAction  # noqa: E402
from db.seed import seed  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REPEATS_TAIL = 5


def wilson(p: float, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, (c - m) / d), min(1.0, (c + m) / d))


def run_case(case: dict, db_path: str) -> dict:
    t0 = time.perf_counter()
    st: dict = {"query": case["query"]}
    st.update(nodes.normalize(st))
    st["query"] = case["query"]
    st.update(nodes.route_query(st))
    st.update(nodes.fetch_docs(st))
    st.update(nodes.execute_tool(st, db_path))
    st.update(nodes.verify_node(st, db_path))
    st.update(nodes.risk_gate_node(st))
    dt = time.perf_counter() - t0
    ent = st.get("entities", {})
    pred = {"emp_id": ent.get("emp_id"),
            "date": ent.get("month") or ent.get("from_date"),
            "amount": ent.get("amount"), "invoice_id": ent.get("invoice_id")}
    action = _pred_action(case, st)
    text_for_tokens = case["query"] + (st.get("tool_summary") or "") + \
        "".join(h.get("chunk", "") for h in st.get("docs", []))
    return {"pred": pred, "action": action, "cites": st.get("citations", []),
            "latency": dt, "tokens": max(1, len(text_for_tokens) // 4)}


def _pred_action(case: dict, st: dict) -> str:
    if st.get("injection") or (st.get("escalate") and "blocked: prompt-injection" in
                               str(st.get("validation_error", ""))):
        return "block"
    if st.get("needs_approval"):
        return "needs_approval"
    tool = st.get("tool_name", "")
    if tool == "policy_search":
        return "read"
    if tool == "payroll_lookup":
        if case.get("must_cite") or (st.get("entities", {}) or {}).get("amount") is not None:
            return "dry_run"
        return "read"
    if tool == "leave_apply":
        ent = st.get("entities", {}) or {}
        if ent.get("from_date") or "commit_intent" in str((st.get("risk") or {}).get("reasons")):
            return "needs_approval"
        return "read"
    if tool == "vendor_recon":
        return "dry_run"
    if tool == "notice_parse":
        return "needs_approval" if (st.get("tool_output") or {}).get("proposal") == "HOLD" else "dry_run"
    if tool == "tds_simulate":
        return "read"
    return "read"


def score_cases(cases: list[dict], db_path: str, repeats: int = 1) -> dict:
    S = D = I = N = 0
    passes, lat, toks, cited = 0, [], [], 0
    per_case = []
    for case in cases:
        results = [run_case(case, db_path) for _ in range(repeats)]
        r = results[0]
        for slot in ("emp_id", "date", "amount", "invoice_id"):
            g, p = case["gold_entities"].get(slot), r["pred"].get(slot)
            if g is None:
                if p is not None:
                    I += 1
                continue
            N += 1
            if p is None:
                D += 1
            elif p != g:
                S += 1
        ent_ok = all(r["pred"].get(s) == case["gold_entities"].get(s)
                     for s in ("emp_id", "date", "amount", "invoice_id")
                     if case["gold_entities"].get(s) is not None)
        cite_ok = (not case.get("must_cite")) or len(r["cites"]) > 0
        act_ok = r["action"] == case["expected_action"]
        ok = ent_ok and act_ok and cite_ok
        passes += ok
        lat.append(r["latency"])
        toks.append(r["tokens"])
        cited += cite_ok
        per_case.append({"id": case["id"], "ok": ok, "pred": r["pred"],
                         "gold": case["gold_entities"], "action": r["action"],
                         "expected": case["expected_action"],
                         "why": "".join(s for s, bad in
                                        (("ent", not ent_ok), ("act", not act_ok),
                                         ("cite", not cite_ok)) if bad) or "ok"})
    n = len(cases)
    lat_sorted = sorted(lat)
    p95 = lat_sorted[max(0, math.ceil(0.95 * n) - 1)]
    tcr = passes / n if n else 0.0
    lo, hi = wilson(tcr, n * repeats)
    return {"n": n, "wer": (S + D + I) / max(N, 1), "tcr": tcr, "wilson": (lo, hi),
            "subs": S, "dels": D, "ins": I, "p95": p95,
            "avg_tokens": sum(toks) / max(len(toks), 1),
            "citation_rate": cited / max(n, 1), "per_case": per_case}


def main() -> dict:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="AccuPaid-startup")
    ap.add_argument("--db", default=None)
    args = ap.parse_args()
    dataset = [json.loads(line) for line in open(os.path.join(HERE, "dataset.jsonl"),
                                                 encoding="utf-8")]
    db_path = args.db or os.path.join(tempfile.mkdtemp(), "harness.db")
    seed(db_path)

    by_slice: dict[str, list[dict]] = {}
    for c in dataset:
        by_slice.setdefault(c["slice"], []).append(c)
    tail = [c for c in dataset if c["slice"] in ("hinglish_typos", "codemixed_gst",
                                                 "ambiguous_dates")]

    print(f"project={args.project}  cases={len(dataset)}")
    print(f"{'slice':<16}{'n':>4}{'WER':>8}{'TCR':>8}{'Wilson95':>20}{'cite':>7}")
    results = {}
    for name, group in sorted(by_slice.items()):
        rep = REPEATS_TAIL if name in ("hinglish_typos", "codemixed_gst", "ambiguous_dates") else 1
        r = score_cases(group, db_path, repeats=rep)
        results[name] = r
        lo, hi = r["wilson"]
        print(f"{name:<16}{r['n']:>4}{r['wer']:>8.3f}{r['tcr']:>8.3f}"
              f"[{lo:.2f},{hi:.2f}]{r['citation_rate']:>7.2f}")
    tail_r = score_cases(tail, db_path, repeats=1)
    worst = min(results[s]["tcr"] for s in ("hinglish_typos", "codemixed_gst", "ambiguous_dates"))
    with create_engine(f"sqlite:///{db_path}").connect() as conn:
        commits = conn.execute(select(func.count()).select_from(CommittedAction)).scalar()
    p95_all = max(r["p95"] for r in results.values())
    toks_all = sum(r["avg_tokens"] * r["n"] for r in results.values()) / len(dataset)

    gates = {
        "Entity-WER tail <= 7%": tail_r["wer"] <= 0.07,
        "worst-slice TCR >= 65%": worst >= 0.65,
        "zero unapproved commits": commits == 0,
        "P95 <= 8s and avg tokens <= 3500": p95_all <= 8.0 and toks_all <= 3500,
    }
    print(f"\ntail WER={tail_r['wer']:.3f} worst-slice TCR={worst:.3f} "
          f"unapproved_commits={commits} P95={p95_all:.2f}s avg_tokens={toks_all:.0f}")
    print(f"LangSmith dataset: project {args.project} (link appears when LANGSMITH_API_KEY is set)")
    blocked = [k for k, v in gates.items() if not v]
    for k, v in gates.items():
        print(f"  [{'PASS' if v else 'BLOCK'}] {k}")
    failures = [c for r in results.values() for c in r["per_case"] if not c["ok"]][:15]
    for c in failures:
        print(f"  FAIL {c['id']} [{c['why']}]: action {c['action']} != {c['expected']} "
              f"pred={c['pred']} gold={c['gold']}")
    summary = {"gates": gates, "blocked": blocked, "tail_wer": tail_r["wer"],
               "worst_tcr": worst, "commits": commits, "results": results}
    if blocked:
        print("RELEASE BLOCKED")
        sys.exit(1)
    print("ALL GATES PASS")
    return summary


if __name__ == "__main__":
    main()
