"""PR17 gates: Temporal ingest — dedupe, quarantine, PII, caps, jobs API."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from workflows import core, service
from workflows.ingest import IngestFileWorkflow, IngestInput, run_inline

PAY = ("emp_id,month,gross,tds,pf,esi,net,pan_number\n"
       "EMP_042,2026-03,110000,11000,1800,0,96200,ABCDE1234F\n"
       "EMP_042,2026-03,99999,11000,1800,0,96200,ABCDE1234F\n"
       "BAD,2026-03,1,1,1,1,1,X\n")


def _env_off(monkeypatch):
    monkeypatch.setenv("TEMPORAL_DISABLED", "1")
    service.reset_client()


def test_workflow_definition_imports():
    assert IngestFileWorkflow.__name__ == "IngestFileWorkflow"
    assert hasattr(IngestFileWorkflow, "run")
    assert hasattr(IngestFileWorkflow, "progress")


def test_content_hash_dedupe(tmp_path, monkeypatch):
    _env_off(monkeypatch)
    dbp = str(tmp_path / "d.db")
    data = PAY.encode()
    maps = {"emp_id": "emp_id", "month": "month", "gross": "gross", "tds": "tds",
            "pf": "pf", "esi": "esi", "net": "net"}
    s1, b1 = asyncio.run(service.submit("p.csv", data, "payroll", maps, dbp))
    assert s1 == 200 and len(b1["job_id"]) == 12
    s2, b2 = asyncio.run(service.submit("p.csv", data, "payroll", {}, dbp))
    assert s2 == 200 and b2["job_id"] == b1["job_id"] and b2.get("deduped_upload") is True


def test_quarantine_and_pii_and_warnings(tmp_path, monkeypatch):
    _env_off(monkeypatch)
    dbp = str(tmp_path / "q.db")
    s, b = asyncio.run(service.submit("p.csv", PAY.encode(), "payroll",
                                      {"emp_id": "emp_id", "month": "month", "gross": "gross",
                                       "tds": "tds", "pf": "pf", "esi": "esi", "net": "net"},
                                      dbp, pii_mode="report"))
    assert s == 200
    assert b["loaded"] == 1 and b["skipped"] == 2  # 1 quarantine + 1 bad id
    assert len(b["quarantined"]) == 1 and "conflicting" in b["quarantined"][0]["reason"]
    assert any(w.startswith("unmapped column") for w in b["warnings"])
    assert any(f["type"] == "PAN" for f in b["pii"]["findings"])
    assert b["mode"] == "inline"


def test_pii_redact_masks(tmp_path, monkeypatch):
    _env_off(monkeypatch)
    from db.pii import apply_redact, redact_value, scan_rows

    assert redact_value("123456789012") == "********9012"
    rows = [{"pan": "ABCDE1234F", "gross": "110000"}]
    scan = scan_rows(rows)
    assert scan["pii_columns"] == ["pan"]
    out, n = apply_redact(rows, ["pan"])
    assert out[0]["pan"] == "******234F" and out[0]["gross"] == "110000" and n == 1
    dbp = str(tmp_path / "r.db")
    emp = b"emp_id,name,dept,ctc,pan_card\nEMP_042,Divya,Engg,1320000,ABCDE1234F\n"
    s, b = asyncio.run(service.submit("e.csv", emp, "employees",
                                      {"emp_id": "emp_id", "name": "name", "dept": "dept",
                                       "ctc": "ctc", "pan_card": "bank_redacted"},
                                      dbp, pii_mode="redact"))
    assert s == 200 and b["pii"]["redacted"] >= 1
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    from db.models import Employee
    with Session(create_engine(f"sqlite:///{dbp}")) as sess:
        emp_row = sess.execute(select(Employee)).scalar_one()
        assert emp_row.ctc == 1320000  # mapped amounts survive redaction
        assert emp_row.bank_redacted != "ABCDE1234F"  # PII masked
    # unknown mapped fields fail fast instead of silently dropping
    s2, b2 = asyncio.run(service.submit("e.csv", emp, "employees",
                                        {"emp_id": "emp_id", "pan_card": "nope_field"},
                                        str(tmp_path / "r2.db")))
    assert s2 == 422 and "unknown employees fields" in b2["detail"]


def test_caps_rejected(tmp_path, monkeypatch):
    _env_off(monkeypatch)
    s, b = asyncio.run(service.submit("big.csv", b"x", "payroll", {}, str(tmp_path / "z.db")))
    assert s == 422  # unparseable / undetectable
    monkeypatch.setattr(core, "MAX_ROWS", 1)
    s2, b2 = asyncio.run(service.submit("a.csv", b"a,b\n1,2\n3,4\n", "payroll",
                                        {"a": "emp_id"}, str(tmp_path / "z2.db")))
    assert s2 == 422 and "too many rows" in b2["detail"]


def test_oversize_file_rejected(tmp_path):
    s, b = asyncio.run(service.submit("big.csv", b"x" * (core.MAX_FILE_MB * 1048576 + 1),
                                      "payroll", {}, str(tmp_path / "z3.db")))
    assert s == 422 and "too large" in b["detail"]


def test_cancel_and_progress_semantics(tmp_path, monkeypatch):
    _env_off(monkeypatch)
    dbp = str(tmp_path / "c.db")
    s, b = asyncio.run(service.submit("p.csv", PAY.encode(), "payroll",
                                      {"emp_id": "emp_id", "month": "month", "gross": "gross",
                                       "tds": "tds", "pf": "pf", "esi": "esi", "net": "net"},
                                      dbp))
    assert s == 200
    p = asyncio.run(service.progress(dbp, b["job_id"]))
    assert p["status"] == "DONE"
    c, cb = asyncio.run(service.cancel(dbp, b["job_id"]))
    assert c == 409 and "already DONE" in cb["detail"]
    c2, _ = asyncio.run(service.cancel(dbp, "nope"))
    assert c2 == 404
    assert asyncio.run(service.progress(dbp, "nope")) is None


def test_run_inline_end_to_end(tmp_path, monkeypatch):
    _env_off(monkeypatch)
    from workflows import core as _core

    dbp = str(tmp_path / "i.db")
    data = b"emp_id,month,gross,tds,pf,esi,net\nEMP_042,2026-03,110000,11000,1800,0,96200\n"
    sha = _core.file_sha(data)
    _core.stage_file(sha, data)
    rep = run_inline(IngestInput(job_id=sha[:12], file_sha=sha, filename="p.csv",
                                mapping={"emp_id": "emp_id", "month": "month", "gross": "gross",
                                         "tds": "tds", "pf": "pf", "esi": "esi", "net": "net"},
                                db_path=dbp))
    assert rep["loaded"] == 1 and rep["mode"] == "inline"


def test_api_temporal_and_cancel_routes():
    import app.main as main
    from fastapi.testclient import TestClient
    from langgraph.checkpoint.memory import MemorySaver

    from agent.graph import build_graph
    from db.seed import seed

    dbp = "test_temporal.db"
    if os.path.exists(dbp):
        os.remove(dbp)
    seed(dbp)
    main.app.state.graph = build_graph(checkpointer=MemorySaver(), db_path=dbp)
    main.app.state.db_path = dbp
    c = TestClient(main.app)
    os.environ["TEMPORAL_DISABLED"] = "1"
    service.reset_client()
    try:
        r = c.post("/ingest/file-temporal", data={"kind": "payroll", "mapping": "",
                                                  "pii": "off"},
                   files={"file": ("p.csv", "emp_id,month,gross,tds,pf,esi,net\nEMP42,2026-03,1,1,1,1,1\n")})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["loaded"] == 1
        d = c.delete(f"/ingest/jobs/{body['job_id']}")
        assert d.status_code == 409
        assert c.delete("/ingest/jobs/nope").status_code == 404
        assert c.get("/").json()["endpoints"].__contains__("/ingest/jobs/{job_id}")
    finally:
        os.environ.pop("TEMPORAL_DISABLED", None)
        service.reset_client()
