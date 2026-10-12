"""PR3 gates: seed counts, strict contracts, read/commit split, idempotency, redaction."""

import os
import sys

import pytest
from pydantic import ValidationError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from db.models import Base, Employee, PayrollRow, VendorInvoice
from db.seed import payroll_row, seed
from mcp_server import server
from mcp_server.guards import (
    normalize_query,
    redact_pii,
    risk_gate,
    sign_approval,
)
from mcp_server.models import (
    ApprovalToken,
    LeaveApplyInput,
    NoticeParseInput,
    PayrollLookupInput,
    SlipParseInput,
    TdsSimulateInput,
    VendorInvoiceReconInput,
)

SECRET = "test-secret-123"


@pytest.fixture()
def db_path(tmp_path):
    p = str(tmp_path / "t.db")
    seed(p)
    return p


def _approve(run_id, reason="ok"):
    return ApprovalToken(run_id=run_id, verdict="approve", reason=reason,
                         signature=sign_approval(run_id, "approve", reason, SECRET))


# --- seed ---

def test_seed_counts(db_path):
    with Session(create_engine(f"sqlite:///{db_path}")) as s:
        assert s.query(Employee).count() == 20
        assert s.query(PayrollRow).count() == 60
        assert s.query(VendorInvoice).count() == 15


def test_demo_anomaly_emp042_mar(db_path):
    mar = server.payroll_lookup(PayrollLookupInput(emp_id="EMP_042", month="2026-03"), db_path)
    feb = server.payroll_lookup(PayrollLookupInput(emp_id="EMP_042", month="2026-02"), db_path)
    assert mar["overtime_hrs"] == 0 and feb["overtime_hrs"] == 8
    assert feb["net"] - mar["net"] > 3000  # missing-overtime diff


def test_payroll_row_formula():
    gross, tds, pf, esi, *_ = payroll_row(1320000, 0, 8)
    assert gross == 110000 and pf == 1800 and esi == 0 and tds == 11000


# --- strict contracts ---

@pytest.mark.parametrize("bad", ["EMP42", "emp_42", "EMP_4", "042"])
def test_emp_regex_rejects(bad):
    with pytest.raises(ValidationError):
        PayrollLookupInput(emp_id=bad, month="2026-03")


@pytest.mark.parametrize("bad", ["INV2041", "inv-2041", "INV-24", "2041"])
def test_inv_regex_rejects(bad):
    with pytest.raises(ValidationError):
        VendorInvoiceReconInput(invoice_id=bad, po_amount=1, invoiced_amount=1,
                                gstin="27ABCDE1234F1Z5")


def test_gstin_regex_rejects():
    with pytest.raises(ValidationError):
        VendorInvoiceReconInput(invoice_id="INV-2041", po_amount=1, invoiced_amount=1,
                                gstin="NOTAGSTIN")


def test_leave_range_rejects():
    with pytest.raises(ValidationError):
        LeaveApplyInput(emp_id="EMP_042", from_date="2026-04-12", to_date="2026-04-10",
                        leave_type="EL")


def test_lookup_missing_row(db_path):
    with pytest.raises(LookupError):
        server.payroll_lookup(PayrollLookupInput(emp_id="EMP_042", month="2020-01"), db_path)


# --- normalization + risk gate ---

def test_normalize_emp_inv():
    text, flags = normalize_query("mera sallery kam ayi EMP42 INV2041?")
    assert "EMP_042" in text and "INV-2041" in text and "salary" in text
    assert flags["emp_norm"] and flags["inv_norm"]


def test_ambiguous_date_flagged():
    _, flags = normalize_query("leave 03/04 se 05/04 tak")
    assert flags.get("ambiguous_date") == "03/04"


def test_risk_gate_forces_approval():
    g = risk_gate(invoiced=73500, po=60000, gst_mismatch=True)
    assert g["needs_approval"] and g["verdict"] == "HOLD" and len(g["reasons"]) == 2
    assert not risk_gate(net_delta=-4200)["needs_approval"]
    assert risk_gate(net_delta=-7800)["needs_approval"]
    assert risk_gate(ambiguous_date=True)["needs_approval"]


def test_redact_pii():
    assert redact_pii("PAN ABCDE1234F aadhaar 1234 5678 9012 acct 12345678901234") == \
        "PAN [PAN] aadhaar [AADHAAR] acct [BANK]"


# --- recon + commit split ---

def test_recon_hold_and_pay(db_path):
    hold = server.vendor_recon(VendorInvoiceReconInput(
        invoice_id="INV-2045", po_amount=60000, invoiced_amount=73500,
        gstin="06UVWXY7890B5Z9"), db_path)
    assert hold["verdict"] == "HOLD" and hold["read_only"]
    pay = server.vendor_recon(VendorInvoiceReconInput(
        invoice_id="INV-2044", po_amount=25000, invoiced_amount=24800,
        gstin="27PQRST3456A4Z1"), db_path)
    assert pay["verdict"] == "PAY" and pay["diff"] == -200


def test_vendor_commit_requires_approval(db_path):
    with pytest.raises(PermissionError):
        server.vendor_commit("r1", "INV-2044",
                             ApprovalToken(run_id="r1", verdict="reject", reason="no",
                                           signature="x"), db_path, SECRET)
    with pytest.raises(PermissionError):  # wrong secret
        server.vendor_commit("r1", "INV-2044", _approve("r1"), db_path, "wrong")


def test_vendor_commit_and_idempotent_double_approve(db_path):
    first = server.vendor_commit("run-9", "INV-2044", _approve("run-9"), db_path, SECRET)
    assert first["committed"] and first["status"] == "APPROVED"
    second = server.vendor_commit("run-9", "INV-2044", _approve("run-9"), db_path, SECRET)
    assert second.get("deduped") is True


def test_vendor_commit_hold_refuses(db_path):
    with pytest.raises(PermissionError):
        server.vendor_commit("run-h", "INV-2045", _approve("run-h"), db_path, SECRET)


def test_leave_draft_and_gated_commit(db_path):
    draft = server.leave_apply(LeaveApplyInput(
        emp_id="EMP_042", from_date="2026-04-10", to_date="2026-04-12", leave_type="EL"))
    assert draft["draft"] and draft["working_days"] == 3
    done = server.commit_leave("run-l", LeaveApplyInput(
        emp_id="EMP_042", from_date="2026-04-10", to_date="2026-04-12", leave_type="EL"),
        _approve("run-l"), db_path, SECRET)
    assert done["committed"]


# --- parse / simulate ---

def test_notice_parse_extracts():
    out = server.notice_parse(NoticeParseInput(
        text="Demand of Rs 45,200 under section 73 due 2026-05-15 for INV-2041 and INV 2045."))
    assert out["demand_amount"] == 45200
    assert out["due_date"] == "2026-05-15" and out["section"] == "73"
    assert "INV-2041" in out["linked_invoices"] and out["proposal"] == "HOLD"


def test_tds_simulate_read_only():
    out = server.tds_simulate(TdsSimulateInput(ctc=1200000, regime="new"))
    assert out["read_only"] and len(out["table"]) == 2
    assert out["delta_new_minus_old"] == out["table"][1]["annual_tax"] - out["table"][0]["annual_tax"]


def test_slip_parse_flags_diff_over_500(db_path):
    actual = server.payroll_lookup(PayrollLookupInput(emp_id="EMP_042", month="2026-03"), db_path)
    out = server.slip_parse(SlipParseInput(emp_id="EMP_042", month="2026-03",
                                           gross=actual["gross"], tds=actual["tds"],
                                           pf=actual["pf"], net=actual["net"] - 5000), db_path)
    assert "net" in out["diffs"] and out["read_only"]


def test_policy_search_shape():
    out = server.policy_search("TDS jyada kata salary")
    assert out["read_only"] and isinstance(out["chunks"], list)
