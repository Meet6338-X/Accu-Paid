"""Graph assembly — durable execution.

Era note (langgraph 0.2.39): this build uses static `interrupt_before` +
`update_state` + `invoke(None, config)` resume, the 0.2.x-correct equivalent of the
spec's `interrupt()` + `Command(resume=...)`. Guarantee is identical: the commit
path cannot execute before a human verdict exists in the checkpoint.

Every invoke uses thread_id=run_id. Replay reads checkpoint via get_state, never memory.
PostgresSaver path for pilot phase: set ACCUPAID_CHECKPOINTER=postgres + POSTGRES_DSN
once the pilot dependency is installed ( Jacobsaver interface is identical).
"""

from __future__ import annotations

import os
import sqlite3
from functools import partial

from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from agent import nodes
from agent.state import AgentState


def _route_after_risk(state: dict) -> str:
    return "human_approval" if state.get("needs_approval") else "format"


def build_graph(checkpointer=None, db_path: str | None = None):
    dbp = db_path or os.getenv("ACCUPAID_DB", "accupaid.db")
    g = StateGraph(AgentState)
    g.add_node("normalize", nodes.normalize)
    g.add_node("router", nodes.route_query)
    g.add_node("fetch_docs", nodes.fetch_docs)
    g.add_node("execute", partial(nodes.execute_tool, db_path=dbp))
    g.add_node("verify", partial(nodes.verify_node, db_path=dbp))
    g.add_node("risk_gate", nodes.risk_gate_node)
    g.add_node("human_approval", nodes.human_approval)
    g.add_node("format", nodes.format_response)
    g.add_edge(START, "normalize")
    g.add_edge("normalize", "router")
    g.add_edge("router", "fetch_docs")
    g.add_edge("fetch_docs", "execute")
    g.add_edge("execute", "verify")
    g.add_edge("verify", "risk_gate")
    g.add_conditional_edges("risk_gate", _route_after_risk,
                            {"human_approval": "human_approval", "format": "format"})
    g.add_edge("human_approval", "format")
    g.add_edge("format", END)
    cp = checkpointer or MemorySaver()
    return g.compile(checkpointer=cp, interrupt_before=["human_approval"])


def sqlite_graph(sqlite_path: str = "checkpoints.db", db_path: str | None = None):
    conn = sqlite3.connect(sqlite_path, check_same_thread=False)
    return build_graph(SqliteSaver(conn), db_path=db_path)


def _config(run_id: str) -> dict:
    return {"configurable": {"thread_id": run_id}}


def run_chat(graph, run_id: str, query: str) -> dict:
    """Invoke once. Returns full state; if paused for approval, state has
    needs_approval=True and result=None (verdict arrives via approve_run)."""
    return graph.invoke({"query": query}, _config(run_id))


def approve_run(graph, run_id: str, verdict: str, reason: str = "") -> dict:
    """Write the human verdict into the checkpoint, then resume. Only 'approve'
    lets human_approval pass; anything else resolves to rejected/blocked."""
    cfg = _config(run_id)
    graph.update_state(cfg, {"human_verdict": verdict, "approval_reason": reason})
    return graph.invoke(None, cfg)


def get_run(graph, run_id: str) -> dict:
    """Full replay from checkpoint — never from process memory."""
    snap = graph.get_state(_config(run_id))
    return dict(snap.values) if snap.values else {}
