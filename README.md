# AccuPaid

Hinglish payroll-dispute + vendor-GST-recon agent with gated execution, human approval, and tail-eval release gates.

> Build spec: [`docs/BUILD-SPEC.md`](docs/BUILD-SPEC.md) (mirrors `idea/AccuPaid-MASTER-PROMPT.md`).
> Idea corpus: [`idea/`](idea/) · Startup plan: [`idea/AccuPaid-STARTUP-PLAN.md`](idea/AccuPaid-STARTUP-PLAN.md)

## Status

Scaffolding in progress — module PRs land one at a time (`app/`, `agent/`, `mcp_server/`, `rag/`, `evals/`, `ui/`, `docs/` site).

## Quickstart (after module PRs land)

```bash
pip install -r requirements.txt
cp .env.example .env
python db/seed.py
uvicorn app.main:app --reload
```

Full README with badges, architecture, tool contracts, and eval table lands with the docs-site PR.
