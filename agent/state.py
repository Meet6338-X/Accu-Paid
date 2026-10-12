"""AgentState — single TypedDict flowing through every node.

Durability rule: the checkpoint (thread_id=run_id) is the source of truth.
GET /runs/{run_id} replays from checkpoint, never from process memory.
"""

from __future__ import annotations

from typing import Literal, TypedDict


class AgentState(TypedDict, total=False):
    query: str
    normalized: str
    flags: dict
    entities: dict  # {emp_id, month, from_date, to_date, amount, invoice_id}
    route: str  # payroll|leave|vendor|notice|simulate|policy
    validation_error: str
    loops: int
    escalate: bool
    docs: list[dict]  # [{doc_id, chunk, cite, score}]
    citations: list[str]
    tool_name: str
    tool_output: dict
    tool_summary: str
    draft: dict  # factual claims awaiting verification
    verification: dict  # CoVe questions/answers, selfcheck flag
    verify_loops: int
    risk: dict  # risk_gate output
    needs_approval: bool
    human_verdict: Literal["approve", "reject"] | None
    approval_reason: str
    committed: dict | None
    result: dict | None
    error: str | None
