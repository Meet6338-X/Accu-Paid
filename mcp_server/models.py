"""Strict Pydantic contracts for all MCP tools.

Raw `EMP42` / `INV2041` are REJECTED here (validation error -> route retry, max 2 loops,
then escalate). Normalization (`EMP42` -> `EMP_042`) happens in `guards.normalize_query`
BEFORE tool calls; the tools themselves only accept canonical IDs.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

EMP_ID_RE = r"^[A-Z]+_[0-9]{3,6}$"
MONTH_RE = r"^\d{4}-\d{2}$"
DATE_RE = r"^\d{4}-\d{2}-\d{2}$"
INV_ID_RE = r"^INV-[0-9]{4,6}$"
GSTIN_RE = r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$"


class PayrollLookupInput(BaseModel):
    emp_id: str = Field(pattern=EMP_ID_RE)
    month: str = Field(pattern=MONTH_RE)  # YYYY-MM


class LeaveApplyInput(BaseModel):
    emp_id: str = Field(pattern=EMP_ID_RE)
    from_date: str = Field(pattern=DATE_RE)
    to_date: str = Field(pattern=DATE_RE)
    leave_type: Literal["CL", "SL", "EL", "LOP"]

    @field_validator("to_date")
    @classmethod
    def _range_ok(cls, v: str, info) -> str:
        if info.data.get("from_date") and v < info.data["from_date"]:
            raise ValueError("to_date must be >= from_date")
        return v


class VendorInvoiceReconInput(BaseModel):
    invoice_id: str = Field(pattern=INV_ID_RE)
    po_amount: float = Field(gt=0)
    invoiced_amount: float = Field(gt=0)
    gstin: str = Field(pattern=GSTIN_RE)


class SlipParseInput(BaseModel):
    """pdf_path path is for OCR deployments; amounts path is for tests/API uploads
    where the caller already extracted cells (each with a confidence)."""

    emp_id: str = Field(pattern=EMP_ID_RE)
    month: str = Field(pattern=MONTH_RE)
    pdf_path: str = ""
    gross: float | None = None
    tds: float | None = None
    pf: float | None = None
    net: float | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class NoticeParseInput(BaseModel):
    text: str = Field(max_length=8000, min_length=1)


class TdsSimulateInput(BaseModel):
    ctc: float = Field(gt=0)
    regime: Literal["old", "new"] = "new"


class ApprovalToken(BaseModel):
    """Signed human verdict. Only `approve` + valid HMAC + unexpired may commit."""

    run_id: str = Field(min_length=1, max_length=64)
    verdict: Literal["approve", "reject"]
    reason: str = Field(default="", max_length=500)
    signature: str = Field(min_length=1)
