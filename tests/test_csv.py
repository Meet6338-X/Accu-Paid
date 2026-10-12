"""PR15 gates: CSV importer — mapping, ID shaping, validation report, upsert."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from db.import_csv import import_csv
from db.models import Employee, PayrollRow, VendorInvoice

EMP_CSV = "emp_id,name,dept,ctc\nEMP42,Test User,Engg,1200000\nBAD ID,Nope,HR,500000\n"
PAY_CSV = ("emp_id,month,gross,tds,pf,esi,net\nEMP_042,2026-03,110000,11000,1800,0,96200\n"
           "EMP42,2026-13,1,1,1,1,1\n")
INV_CSV = ("invoice_id,vendor,po_amount,invoiced_amount,gstin\nINV2041,Acme,45000,45200,"
           "27ABCDE1234F1Z5\nINV-9,Bad,1,1,NOPE\n")


def _fresh(tmp_path, name="c.db"):
    return str(tmp_path / name)


def test_employees_shape_and_skip(tmp_path):
    rep = import_csv(EMP_CSV, "employees",
                     {"emp_id": "emp_id", "name": "name", "dept": "dept", "ctc": "ctc"},
                     _fresh(tmp_path))
    assert rep["kind"] == "employees" and rep["total"] == 2
    assert rep["loaded"] == 1 and rep["skipped"] == 1 and rep["job_id"]
    assert rep["errors"][0]["row"] == 3  # BAD ID
    with Session(create_engine(f"sqlite:///{_fresh(tmp_path)}")) as s:
        assert s.execute(select(Employee).where(Employee.emp_id == "EMP_042")).scalar_one()


def test_payroll_month_default_and_bad_month(tmp_path):
    dbp = _fresh(tmp_path)
    rep = import_csv("emp_id,gross,tds,pf,esi,net\nEMP_042,110000,11000,1800,0,96200\n",
                     "payroll", {"emp_id": "emp_id", "gross": "gross", "tds": "tds",
                                 "pf": "pf", "esi": "esi", "net": "net"},
                     dbp, month_default="2026-03")
    assert rep["loaded"] == 1 and rep["skipped"] == 0
    rep2 = import_csv(PAY_CSV, "payroll",
                      {"emp_id": "emp_id", "month": "month", "gross": "gross", "tds": "tds",
                       "pf": "pf", "esi": "esi", "net": "net"}, dbp)
    assert rep2["loaded"] == 1 and rep2["skipped"] == 1  # 2026-13 invalid


def test_invoices_shape_gstin_and_upsert(tmp_path):
    dbp = _fresh(tmp_path)
    m = {"invoice_id": "invoice_id", "vendor": "vendor", "po_amount": "po_amount",
         "invoiced_amount": "invoiced_amount", "gstin": "gstin"}
    rep = import_csv(INV_CSV, "invoices", m, dbp)
    assert rep["loaded"] == 1 and rep["skipped"] == 1
    rep2 = import_csv(INV_CSV, "invoices", m, dbp)  # upsert, no dupes
    assert rep2["loaded"] == 1
    with Session(create_engine(f"sqlite:///{dbp}")) as s:
        n = s.execute(select(func.count()).select_from(VendorInvoice)).scalar()
        assert n == 1


def test_validate_only_writes_nothing(tmp_path):
    dbp = _fresh(tmp_path)
    rep = import_csv(EMP_CSV, "employees",
                     {"emp_id": "emp_id", "name": "name", "dept": "dept", "ctc": "ctc"},
                     dbp, validate_only=True)
    assert rep["loaded"] == 0 and rep["total"] == 2
    with Session(create_engine(f"sqlite:///{dbp}")) as s:
        assert s.query(Employee).count() == 0


def test_api_csv_upload_roundtrip():
    import app.main as main
    from fastapi.testclient import TestClient
    from langgraph.checkpoint.memory import MemorySaver

    from agent.graph import build_graph
    from db.seed import seed

    dbp = "test_csv.db"
    if os.path.exists(dbp):
        os.remove(dbp)
    seed(dbp)
    main.app.state.graph = build_graph(checkpointer=MemorySaver(), db_path=dbp)
    main.app.state.db_path = dbp
    c = TestClient(main.app)
    import json as _json
    r = c.post("/ingest/csv",
               data={"kind": "payroll",
                     "mapping": _json.dumps({"emp_id": "emp_id", "gross": "gross", "tds": "tds",
                                             "pf": "pf", "esi": "esi", "net": "net"}),
                     "month_default": "2026-03"},
               files={"file": ("pay.csv", "emp_id,gross,tds,pf,esi,net\nEMP_042,110000,11000,1800,0,96200\n")})
    assert r.status_code == 200, r.text
    assert r.json()["loaded"] == 1
    q = c.post("/chat", json={"query": "Show payroll for EMP_042 for 2026-03."})
    assert q.json()["status"] == "answered"
