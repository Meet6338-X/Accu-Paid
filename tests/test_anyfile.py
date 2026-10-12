"""PR16 gates: any-file parse, AI/heuristic mapping, durable jobs."""

import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.anyfile import detect_kind, heuristic_mapping, infer_mapping, parse_file
from db.import_csv import import_rows


def _rows():
    return [{"Employee ID": "42", "Monthly Income": "110000", "Tax": "11000",
             "PF Fund": "1800", "ESI": "0", "Net Pay": "96200", "Pay Month": "Mar 2026"}]


def test_parse_xlsx_and_json(tmp_path):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["emp_id", "month", "gross", "tds", "pf", "esi", "net"])
    ws.append(["EMP_042", "2026-03", 110000, 11000, 1800, 0, 96200])
    buf = io.BytesIO()
    wb.save(buf)
    rows = parse_file("pay.xlsx", buf.getvalue())
    assert rows[0]["emp_id"] == "EMP_042" and rows[0]["month"] == "2026-03"
    jrows = parse_file("pay.json", json.dumps({"rows": rows}).encode())
    assert jrows == rows
    try:
        parse_file("pay.exe", b"x")
        assert False, "must reject"
    except ValueError:
        pass


def test_heuristic_mapping_aliases():
    kind, mapping, via = infer_mapping(None, _rows())
    assert kind == "payroll" and via == "heuristic"
    assert mapping["Employee ID"] == "emp_id"
    assert mapping["Monthly Income"] == "gross"
    assert mapping["Net Pay"] == "net"
    assert mapping["Pay Month"] == "month"


def test_llm_mapping_preferred_when_available(monkeypatch):
    import llm.client as llm

    monkeypatch.setattr(llm, "complete",
                        lambda *a, **k: '{"Employee ID": "emp_id", "Monthly Income": "gross"}')
    kind, mapping, via = infer_mapping("payroll", _rows())
    assert via == "llm" and mapping == {"Employee ID": "emp_id", "Monthly Income": "gross"}


def test_import_rows_month_shapes_and_job_ledger(tmp_path):
    dbp = str(tmp_path / "j.db")
    rep = import_rows(_rows(), "payroll",
                      {"Employee ID": "emp_id", "Monthly Income": "gross", "Tax": "tds",
                       "PF Fund": "pf", "ESI": "esi", "Net Pay": "net", "Pay Month": "month"},
                      dbp, filename="hr.xlsx")
    assert rep["loaded"] == 1 and rep["job_id"] and len(rep["job_id"]) == 12
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    from db.models import IngestJob, PayrollRow
    with Session(create_engine(f"sqlite:///{dbp}")) as s:
        row = s.execute(select(PayrollRow)).scalar_one()
        assert (row.emp_id, row.month) == ("EMP_042", "2026-03")
        job = s.execute(select(IngestJob)).scalar_one()
        assert job.status == "DONE" and job.filename == "hr.xlsx" and job.total == 1


def test_api_file_and_job_roundtrip():
    import app.main as main
    from fastapi.testclient import TestClient
    from langgraph.checkpoint.memory import MemorySaver

    from agent.graph import build_graph
    from db.seed import seed

    dbp = "test_any.db"
    if os.path.exists(dbp):
        os.remove(dbp)
    seed(dbp)
    main.app.state.graph = build_graph(checkpointer=MemorySaver(), db_path=dbp)
    main.app.state.db_path = dbp
    c = TestClient(main.app)
    r = c.post("/ingest/file", data={"kind": "", "mapping": ""},
               files={"file": ("pay.csv", "emp_id,month,gross,tds,pf,esi,net\nEMP42,2026-03,110000,11000,1800,0,96200\n")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["loaded"] == 1 and body["mapping_via"] in ("llm", "heuristic")
    j = c.get(f"/ingest/jobs/{body['job_id']}")
    assert j.status_code == 200 and j.json()["status"] == "DONE"
    assert c.get("/ingest/jobs/nope").status_code == 404
