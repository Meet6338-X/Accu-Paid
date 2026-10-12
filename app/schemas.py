"""API contracts — ChatRequest, ApproveRequest, SlipDiff, NoticeParse."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)


class ApproveRequest(BaseModel):
    verdict: Literal["approve", "reject"]
    reason: str = Field(default="", max_length=500)
    signature: str = Field(min_length=1)


class SlipIngest(BaseModel):
    emp_id: str = Field(pattern=r"^[A-Z]+_[0-9]{3,6}$")
    month: str = Field(pattern=r"^\d{4}-\d{2}$")
    gross: float | None = None
    tds: float | None = None
    pf: float | None = None
    net: float | None = None


class NoticeIngest(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
