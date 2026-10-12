"""PR5 gates: chat/approve/replay/audit/ingest over HTTP."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("APPROVAL_HMAC_SECRET", "test-api-secret")

from fastapi.testclient import TestClient

import app.main as main
from db.seed import seed

DB = "test_api.db"
if os.path.exists(DB):
    os.remove(DB)
seed(DB)
os.environ["ACCUPAID_DB"] = DB

from langgraph.checkpoint.memory import MemorySaver  # noqa: E402

from agent.graph import build_graph  # noqa: E402

main.app.state.graph = build_graph(checkpointer=MemorySaver(), db_path=DB)
main.app.state.db_path = DB
client = TestClient(main.app)


def test_root_and_health():
    r = client.get("/")
    assert r.status_code == 200
    body = r.json()
    assert body["service"] == "AccuPaid" and body["status"] == "ok"
    assert "/chat" in body["endpoints"] and "/health" in body["endpoints"]
    h = client.get("/health")
    assert h.status_code == 200
    hb = h.json()
    assert hb["status"] == "ok" and hb["db"] is True and hb["graph"] is True
    assert hb["llm"]["fallback"] == "pollinations:available"


def test_every_route_method_matrix():
    # Cross-check: every documented endpoint responds (never 404), wrong verbs 405.
    r = client.post("/chat", json={"query": "Show payroll for EMP_007 for 2026-01."})
    assert r.status_code == 200
    run_id = r.json()["run_id"]
    assert client.get(f"/runs/{run_id}").status_code == 200
    assert client.get(f"/runs/{run_id}/audit").status_code == 200
    assert client.get(f"/runs/{run_id}/audit", params={"format": "csv"}).status_code == 200
    assert client.get("/chat").status_code == 405
    assert client.post(f"/runs/{run_id}").status_code == 405
    assert client.get("/ingest/slip").status_code == 405
    assert client.get("/ingest/notice").status_code == 405
    assert client.get("/nope").status_code == 404


def test_chat_read_answers_and_replays():
    r = client.post("/chat", json={"query": "Show payroll for EMP_042 for 2026-03."})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "answered"
    run_id = body["run_id"]
    g = client.get(f"/runs/{run_id}")
    assert g.status_code == 200
    assert g.json()["state"]["result"]["entities"]["emp_id"] == "EMP_042"


def test_chat_demo_query():
    r = client.post("/chat", json={"query": "mera march ki salary kam ayi, TDS jyada kata? EMP_042"})
    assert r.status_code == 200
    assert r.json()["status"] in ("answered", "needs_approval")


def test_notice_hold_needs_approval_then_reject():
    r = client.post("/chat", json={"query": "Parse this notice: demand of Rs 45,200 under "
                                            "section 73 due 2026-05-15 for INV-2041."})
    assert r.json()["status"] == "needs_approval"
    run_id, sig = r.json()["run_id"], r.json()["reject_signature"]
    a = client.post(f"/approve/{run_id}", json={"verdict": "reject", "reason": "not ours",
                                                "signature": sig})
    assert a.status_code == 200
    assert a.json()["status"] == "rejected"


def test_approve_bad_signature_forbidden():
    r = client.post("/chat", json={"query": "Parse this notice: demand of Rs 45,200 under "
                                            "section 73 due 2026-05-15 for INV-2041."})
    run_id = r.json()["run_id"]
    a = client.post(f"/approve/{run_id}", json={"verdict": "approve", "reason": "",
                                                "signature": "forged"})
    assert a.status_code == 403


def test_leave_approve_to_commit_idempotent():
    r = client.post("/chat", json={"query": "Apply EL leave for EMP_042 from 2026-04-10 "
                                            "to 2026-04-12."})
    assert r.json()["status"] == "needs_approval", r.text
    run_id, sig = r.json()["run_id"], r.json()["approve_signature"]
    a1 = client.post(f"/approve/{run_id}", json={"verdict": "approve", "reason": "",
                                                 "signature": sig})
    assert a1.json()["status"] == "committed", a1.text
    assert a1.json()["result"]["commit"]["committed"] is True


def test_vendor_hold_approve_stays_held():
    r = client.post("/chat", json={"query": "Pay INV-2045 now, PO 60000 invoiced 73500."})
    body = r.json()
    assert body["status"] == "needs_approval", body
    a = client.post(f"/approve/{body['run_id']}",
                    json={"verdict": "approve", "reason": "",
                          "signature": body["approve_signature"]})
    assert a.json()["status"] == "approved_hold", a.text
    assert a.json()["result"]["commit"]["committed"] is False


def test_unknown_run_404():
    assert client.get("/runs/nope").status_code == 404
    assert client.get("/runs/nope/audit").status_code == 404


def test_audit_json_and_csv():
    r = client.post("/chat", json={"query": "Show payroll for EMP_007 for 2026-01."})
    run_id = r.json()["run_id"]
    j = client.get(f"/runs/{run_id}/audit")
    assert j.status_code == 200 and j.json()["audit"]
    c = client.get(f"/runs/{run_id}/audit", params={"format": "csv"})
    assert "field,value" in c.json()["csv"]


def test_ingest_endpoints():
    s = client.post("/ingest/slip", json={"emp_id": "EMP_042", "month": "2026-03",
                                          "gross": 110000, "tds": 11000, "pf": 1800,
                                          "net": 50000})
    assert s.status_code == 200 and "net" in s.json()["diffs"]
    n = client.post("/ingest/notice", json={"text": "Demand Rs 45,200 section 73 "
                                                   "due 2026-05-15 INV-2041"})
    assert n.json()["demand_amount"] == 45200


def test_cors_preflight_from_console():
    # Browser preflight (the 405s in uvicorn logs): must pass with ACAO header.
    r = client.options("/health", headers={"Origin": "http://127.0.0.1:8501",
                                           "Access-Control-Request-Method": "GET"})
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == "http://127.0.0.1:8501"
    p = client.post("/chat", json={"query": "Show payroll for EMP_007 for 2026-01."},
                    headers={"Origin": "http://127.0.0.1:8501"})
    assert p.status_code == 200
    assert p.headers.get("access-control-allow-origin") == "http://127.0.0.1:8501"
