"""PR4 gates: node pipeline, CoVe verify, risk routing, interrupt + resume + replay."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langgraph.checkpoint.memory import MemorySaver

from agent import nodes
from agent.graph import approve_run, build_graph, get_run, run_chat
from db.seed import seed


def _graph(tmp_path):
    dbp = str(tmp_path / "a.db")
    seed(dbp)
    return build_graph(checkpointer=MemorySaver(), db_path=dbp)


DEMO_Q = "mera march ki salary kam ayi, TDS jyada kata? EMP_042"


def test_normalize_demo_query():
    s = nodes.normalize({"query": DEMO_Q})
    assert s["entities"]["emp_id"] == "EMP_042"
    assert s["entities"]["month"] == "2026-03"
    assert "salary" in s["normalized"]


def test_route_payroll_and_validation_loop_escalates():
    s = {"normalized": "show salary", "flags": {}, "entities": {"emp_id": None}, "loops": 0}
    r1 = nodes.route_query(s)
    assert r1["route"] == "payroll" and r1["loops"] == 1 and not r1.get("escalate")
    r2 = nodes.route_query({**s, "loops": 1})
    assert r2.get("escalate") is True  # max 2 loops then human


def test_ambiguous_date_assumed_ddmm_and_gated():
    s = nodes.normalize({"query": "leave 03/04 se 05/04 tak EMP_042 ka EL lagao"})
    assert s["flags"].get("ambiguous_date") == "03/04"
    assert s["entities"]["from_date"] == "2026-04-03"  # IN-locale DD/MM assumption
    assert s["flags"].get("date_assumed")
    r = nodes.route_query({**s, "query": "leave 03/04 se 05/04 tak EMP_042 ka EL lagao"})
    assert not r.get("escalate")
    g = nodes.risk_gate_node({**s, "tool_output": {"draft": True}, "verification": {}})
    assert g["needs_approval"] is True  # assumption always surfaces for human confirm


def test_read_path_answers_without_approval(tmp_path):
    g = _graph(tmp_path)
    st = run_chat(g, "run-read", "Show payroll for EMP_042 for 2026-03 with gross, TDS, PF and net pay.")
    assert st.get("needs_approval") is False
    assert st["result"]["status"] == "answered"
    assert st["result"]["entities"]["emp_id"] == "EMP_042"


def test_demo_query_dry_run_result(tmp_path):
    g = _graph(tmp_path)
    st = run_chat(g, "run-demo", DEMO_Q)
    assert st["result"]["status"] in ("answered", "needs_approval")
    assert st["result"]["entities"] == {"emp_id": "EMP_042", "month": "2026-03",
                                        "from_date": None, "to_date": None,
                                        "amount": None, "invoice_id": None}


def test_full_replay_from_checkpoint(tmp_path):
    g = _graph(tmp_path)
    run_chat(g, "run-replay", DEMO_Q)
    replay = get_run(g, "run-replay")
    assert replay["query"] == DEMO_Q
    assert replay["result"]["entities"]["emp_id"] == "EMP_042"


def test_verify_recheck_confirms_amounts(tmp_path):
    dbp = str(tmp_path / "v.db")
    seed(dbp)
    st = {"query": "Show payroll for EMP_042 for 2026-03",
          "normalized": "show payroll for emp_042 for 2026-03",
          "flags": {}, "entities": {"emp_id": "EMP_042", "month": "2026-03"},
          "route": "payroll", "tool_name": "payroll_lookup"}
    st.update(nodes.execute_tool(st, dbp))
    v = nodes.verify_node(st, dbp)
    assert v["verification"]["verdict"] == "ok"  # independent recheck agrees
    assert v["verification"]["problems"] == []


def test_human_approval_blocks_without_verdict():
    out = nodes.human_approval({"human_verdict": None})
    assert out["result"]["status"] == "blocked"


def test_risk_hold_routes_to_approval_node(tmp_path):
    g = _graph(tmp_path)
    # EMP_025 Mar has the approval-forcing net drop; force a recon-style HOLD via notice path
    st = run_chat(g, "run-hold", "Parse this notice: demand of Rs 45,200 under section 73 "
                                 "due 2026-05-15 for INV-2041.")
    assert st.get("needs_approval") is True
    assert st.get("result") is None  # paused before human_approval
    resumed = approve_run(g, "run-hold", "reject", "not our invoice")
    assert resumed["result"]["status"] == "rejected"
