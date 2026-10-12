# AccuPaid

[![CI](https://github.com/Meet6338-X/Accu-Paid/actions/workflows/ci.yml/badge.svg)](https://github.com/Meet6338-X/Accu-Paid/actions)
[![Python](https://img.shields.io/badge/python-3.11-blue)](requirements.txt)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688)](app/main.py)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.2.x-orange)](agent/graph.py)
[![License](https://img.shields.io/badge/license-MIT-lightgrey)](LICENSE)
[![Gates](https://img.shields.io/badge/gates-4%2F4_passing-brightgreen)](evals/harness.py)

Hinglish payroll-dispute + vendor-GST-recon agent with gated tool execution, human approval, and tail-eval release gates.

> Build spec: [`docs/BUILD-SPEC.md`](docs/BUILD-SPEC.md) (mirrors `idea/AccuPaid-MASTER-PROMPT.md`).
> Idea: [`idea/ideas/accupaid.md`](idea/ideas/accupaid.md) · Startup plan: [`idea/AccuPaid-STARTUP-PLAN.md`](idea/AccuPaid-STARTUP-PLAN.md) · Findings: [`idea/REDDIT-FINDINGS.md`](idea/REDDIT-FINDINGS.md)
> Marketing site: [`docs/`](docs/) (GitHub Pages) — pilot requests go to the site form.

## What is AccuPaid

AccuPaid helps HR/payroll ops at 50–500-person Indian SMEs on Keka/Zoho People resolve code-mixed Hinglish salary disputes and vendor GST recon without hallucinated emp_ids, dates, or amounts: a FastAPI gateway fronts a LangGraph supervisor (SQLite checkpointer) that normalizes the query, routes intent, retrieves cited PF/ESI/TDS/GST policy chunks, dry-runs a strictly-typed MCP tool, Chain-of-Verification-checks the draft, applies a deterministic risk gate, and blocks every money-moving commit behind a signed human-approval interrupt with a full audit trail.

**Demo moment (< 60s):** type `mera march ki salary kam ayi, TDS jyada kata? EMP_042` (typo) → normalized query + retrieved TDS chunk with `[doc:chunk]` cite + dry-run diff → press **Approve** → commit + audit row + trace.

## Architecture

```text
POST /chat ──► normalize ──► route ──► fetch_docs (top-k 5, cap 1800 tok)
                                      (validation error → retry route, max 2 loops → escalate)
                   ▼
             execute_tool (MCP, read/dry-run only) ──► verify_node (CoVe + CRITIC recheck
                                                          + SelfCheckGPT 3x, max 2 loops)
                   ▼
             risk_gate (deterministic Python: amount > 10000 | GST mismatch |
                        net-pay Δ > 5000 | date assumption | commit intent → needs_approval)
                   ▼
             human_approval (LangGraph interrupt_before, thread_id = run_id)
                approve → gated commit + ledger + audit export
                reject / expired / none → no commit, ever
                   ▼
             format_response (atomic claims + [doc:chunk] cites)
```

- **Checkpointer:** every invoke uses `thread_id=run_id`. `POST /approve/{run_id}` writes the verdict with `update_state` and resumes via `invoke(None, config)` (the 0.2.39-era-correct equivalent of `interrupt()` + `Command(resume=...)`). `GET /runs/{run_id}` replays from checkpoint, never from memory. Pilot path: Postgres checkpointer (same saver interface).
- **Read vs commit split:** `payroll_lookup`, `leave_apply` (draft), `vendor_recon`, `policy_search`, `slip_parse`, `notice_parse`, `tds_simulate` are read/dry-run and never move money. `vendor_commit` / `commit_leave` require `human_verdict == approve` + valid HMAC + idempotency key `run_id+tool+hash(args)`. Double-approve is a ledger-hit no-op. PAY-able commits execute on approval; HOLD (GST mismatch / amount breach) stays held for CA review.
- **Injection defense:** scraped text is data, never instructions — override/skip-approval/fake-approver patterns block with zero commit calls.

## MCP tool contracts

Server: [`mcp_server/server.py`](mcp_server/server.py) · Strict models: [`mcp_server/models.py`](mcp_server/models.py) · Guards: [`mcp_server/guards.py`](mcp_server/guards.py)

| # | Tool | Class | Contract highlights |
|---|------|-------|---------------------|
| 1 | `payroll_lookup` | read | `emp_id ^[A-Z]+_[0-9]{3,6}$`, `month ^\d{4}-\d{2}$`; raw `EMP42` rejected, normalized before call |
| 2 | `leave_apply` | read (draft) | `from/to_date ^\d{4}-\d{2}-\d{2}$`, `CL/SL/EL/LOP`, `to >= from`; writes nothing, commit via `commit_leave` |
| 3 | `vendor_recon` | read (dry-run) | `invoice_id ^INV-[0-9]{4,6}$`, `po/invoiced > 0`, GSTIN regex; returns `HOLD/PAY` + risk score |
| 4 | `vendor_commit` | **commit** | `(run_id, invoice_id, ApprovalToken)`; refuses HOLD invoices; idempotent ledger |
| 5 | `policy_search` | read | keyword search over `rag/policy_docs/*.md` → `[doc_id:chunk]` cites; e5+Qdrant pilot path in `rag/ingest.py` |
| 6 | `slip_parse` | read | extracted cells or `pdf_path`; diffs vs `payroll_lookup`, flags diffs > INR 500 |
| 7 | `notice_parse` | read | `text 1..8000 chars` → `demand_amount/due_date/section/linked_invoices`; HOLD only over 10000 |
| 8 | `tds_simulate` | read | `ctc > 0`, `regime old/new` → old-vs-new delta table, `read_only: true` |

`ApprovalToken`: `run_id + verdict (approve/reject) + reason (≤500) + HMAC signature`, 15-min expiry. Only `approve` + valid + unexpired may commit.

## Quickstart

```bash
pip install -r requirements.txt
cp .env.example .env          # Windows: copy .env.example .env
python db/seed.py             # 20 employees + 60 payroll rows + 15 invoices (SQLite)
uvicorn app.main:app --reload # API :8000 — /chat, /approve, /runs, /ingest, /health
cd frontend && npm install && npm run dev   # console :8501 (chat, runs, ingest, health)
python evals/harness.py       # release gates (see below)
# ...or double-click start.bat (Windows) for API + console together.
```

Endpoints (`app/main.py`): `GET /`, `GET /health`, `POST /chat`, `POST /approve/{run_id}`, `GET /runs/{run_id}`, `GET /runs/{run_id}/audit` (JSON/CSV), `POST /ingest/slip`, `POST /ingest/notice`. Interactive console (`frontend/`, React+Vite): live pipeline chat, approval cards with expiry countdown, run replay timeline, slip/notice ingest, endpoint cross-check. ChatOps stubs (`ui/chatops.py`): signed Slack/WhatsApp approve buttons. LLM (`llm/client.py`): OpenRouter primary, Pollinations.ai free fallback, offline-safe; set `OPENROUTER_API_KEY` + `ACCUPAID_LLM_ENHANCE=1` for summary polish, else pure rule-based. Env: `OPENROUTER_API_KEY`, `LLM_MODEL`, `LANGSMITH_API_KEY`, `QDRANT_URL`, `MCP_URL`, `APPROVAL_HMAC_SECRET`.

## Import your data (any file)

`POST /ingest/file` takes **csv, xlsx/xls, json, txt, md, pdf**. Omit the
mapping and the AI maps your columns (LLM, else an offline alias table); omit
the kind and it auto-detects employees/payroll/invoices. Unstructured text/pdf
needs a model to structure rows — without one it says so instead of guessing.

```bash
# xlsx, no mapping, no kind — AI figures it out, preview only
curl -X POST http://127.0.0.1:8000/ingest/file \
  -F validate_only=true \
  -F file=@salaries.xlsx
# {"job_id":"a1b2c3...","kind":"payroll","total":60,"loaded":0,"skipped":2,
#  "mapping_via":"llm","errors":[...]}
```

Durable: every upload is a **job** — chunked commits (200 rows), natural-key
upserts, persisted report at `GET /ingest/jobs/{job_id}`. Crash mid-file?
Re-submit the same file; finished chunks survive, the rest fills in. Rules: IDs
auto-shape (`EMP42`/`42` → `EMP_042`); months accept `2026-03`, `03/2026`,
`Mar 2026`; amounts tolerate `₹`/commas/decimals. Console → Ingest tab has the
same flow with a mapping editor and error table. (`POST /ingest/csv` still
works for explicit CSV loads.)

## Evals (Sarvam gates — measured, reproducible)

Dataset: `evals/dataset.jsonl` (120 cases: 60 clean, 48 tail Hinglish+typo, 12 adversarial). Each tail case runs **5×**, Wilson 95% CI reported; point pass rates rejected. Entity-WER = `(sub+del+ins)/slots` over `{emp_id, date, amount, invoice_id}`; amounts exact-match as integers. Case passes iff entities exact AND action exact AND (`must_cite` → cite present).

Measured 2026-10-12 via `python evals/harness.py --project AccuPaid-startup`:

| Slice | n | Entity-WER | TCR | Wilson 95% |
|---|---|---|---|---|
| clean | 60 | 0.000 | 1.000 | [0.94, 1.00] |
| hinglish_typos | 24 | 0.000 | 1.000 | [0.97, 1.00] |
| codemixed_gst | 12 | 0.000 | 1.000 | [0.94, 1.00] |
| ambiguous_dates | 12 | 0.000 | 1.000 | [0.94, 1.00] |
| adversarial | 12 | 0.000 | 1.000 | [0.76, 1.00] |

| Gate (BLOCK = do not ship) | Threshold | Measured |
|---|---|---|
| Entity-WER, tail | ≤ 7% | **0.000** ✅ |
| Worst-slice TCR | ≥ 65% | **1.000** ✅ |
| Unapproved commits | 0 | **0** ✅ |
| P95 latency / avg tokens | ≤ 8s / ≤ 3500 | **3.03s / 175** ✅ |

Tail traps covered: `sallery`, `EMP42→EMP_042`, `INV2041→INV-2041`, `03/04→DD/MM+approval`, `45,200→45200`, injection block. Details: [`evals/tail_cases.md`](evals/tail_cases.md).

## Repo layout

```text
app/            # main.py (/chat, /approve, /runs, /ingest), schemas.py
agent/          # state.py, nodes.py (normalize/route/fetch/execute/verify/risk/approval/format), graph.py
mcp_server/     # server.py (8 tools), models.py (strict Pydantic), guards.py (risk/HMAC/idempotency)
rag/            # ingest.py (350-tok chunks, 50 overlap), policy_docs/ (PF/ESI/TDS/GST/LOP/overtime/glossary)
db/             # models.py, seed.py (deterministic SQLite seed)
evals/          # harness.py, build_dataset.py, dataset.jsonl (120), tail_cases.md
ui/             # chatops.py (Slack/WhatsApp signed-button stubs)
frontend/       # React+Vite console (chat, runs, ingest, health) on :8501
tests/          # test_data_tools/agent/api/rag/evals/ui.py — 57 tests
docs/           # BUILD-SPEC.md + marketing site (index.html, styles.css, app.js) for GitHub Pages
idea/           # accupaid.md, STARTUP-PLAN, MASTER-PROMPT, REDDIT-FINDINGS, panel, research index
```

## Guardrails

- **PII redaction:** PAN/Aadhaar/bank regex scrubbed before any log/trace.
- **Timeouts/retries:** per-tool 25s timeout, tenacity 3× exponential on DB calls; validation errors loop to route max 2× then escalate.
- **Approval expiry:** links expire in 15 min, HMAC-signed; commit key = `run_id+tool+hash(args)`; double-approve deduped.
- **Context discipline:** docs capped 1800 tokens, tool outputs summarized over 800 tokens, Hindi 3× fertility assumed; constitution string: *never commit money without `human_verdict == approve`* — enforced in Python, no prompt may override it.

## Kill criteria

[`idea/ideas/accupaid.md`](idea/ideas/accupaid.md) § Kill Criteria + [`idea/AccuPaid-STARTUP-PLAN.md`](idea/AccuPaid-STARTUP-PLAN.md) § Kill triggers: Entity-WER tail > 7% after 2 prompt iterations, worst-slice TCR < 65%, any unapproved commit path in traces, P95 > 8s on free-tier LLM, or 3 pilots refusing paid conversion after time-saved proof. Thresholds are never lowered to pass — kill/pivot instead.

## Contact

Pilot requests: the form on the [marketing site](https://meet6338-x.github.io/Accu-Paid/) (delivered via FormSubmit). Pricing: pilot free 30d/100 emp; then INR 199/HR seat/mo + INR 15/recon over 200/mo.

## License

MIT — see [LICENSE](LICENSE).
