# AccuPaid User Manual

> For HR/payroll operators, CAs, and pilot admins. Technical build spec: `docs/BUILD-SPEC.md`. Quickstart: `README.md`.

## 1. What AccuPaid does

You type a salary question in normal Hinglish — typos welcome (`mera march ki salary kam ayi, TDS jyada kata? EMP_042`). AccuPaid normalizes it, looks up the real payroll row, cites the policy rule, shows a **dry-run diff**, and waits for your **Approve**. Nothing that moves money executes without a signed human approval, and every step is saved for audit.

---

## 2. What data we use

| Data | Where it lives | What it is | Who provides it |
|---|---|---|---|
| Demo seed | `accupaid.db` (SQLite, gitignored) | 20 employees, 60 payroll rows (Jan–Mar 2026), 15 vendor invoices. Pay computed by fixed formulas (`gross=ctc/12`, PF capped 1800, slab TDS). Created by `python db/seed.py`. | Built-in demo |
| Policy docs | `rag/policy_docs/` (7 files) | PF, ESI, TDS old-vs-new, GST mismatch, LOP, overtime, glossary — 10 atomic facts each, all thresholds configurable | Built-in |
| Eval dataset | `evals/dataset.jsonl` | 120 test cases (60 clean, 48 Hinglish tail, 12 adversarial). Proves the gates; not user data | Built-in |
| Temp research data | `data/external/` (gitignored) | IBM HR sample (1470 rows) for realism spot-checks only. Never enters payroll | Downloaded sample |
| **Your data** | `accupaid.db` (same tables) | Your employees/payroll/invoices via Ingest (§5.3). Replaces or extends the seed | You |
| Run checkpoints | `checkpoints.db` / memory | Every query's pipeline state, keyed by `run_id`. Powers replay + approve-resume | Generated |
| Ledgers | `accupaid.db` tables | `committed_actions` (idempotency: double-approve = no-op), `ingest_jobs` (every upload + report) | Generated |
| Upload staging | `data/staging/` (gitignored) | Raw uploaded bytes, hashed by content | Generated |
| Secrets | `.env` (never committed) | API keys, HMAC secret. Template: `.env.example` | You |

**What we never store:** PAN, Aadhaar, bank/account numbers are redacted before any log or trace, and ingest can mask them at load (`pii=redact`). Only redacted tails (e.g. `XXXX-XXXX-1142`) live in the seed.

---

## 3. How everything works

### 3.1 The pipeline (every query goes through this)

```text
your words → normalize (fix sallery/EMP42/INV2041/03-04)
          → route (payroll / leave / vendor / notice / simulate / policy)
          → fetch_docs (top-5 policy chunks, max 1800 tokens)
          → execute_tool (READ-ONLY: lookup, recon dry-run, parse, simulate)
          → verify (re-check amounts with independent re-query, max 2 loops)
          → risk_gate (deterministic: amount>10000, GST mismatch, net Δ>5000,
                       date assumption, pay/apply intent → needs approval?)
          → human_approval (graph PAUSES here if approval needed)
          → format_response (summary + atomic [doc:chunk] cites)
```

Key facts: validation errors retry routing max 2× then escalate to you. Slash dates (`03/04`) are assumed DD/MM (Indian locale) **and** always force approval — never silent. Prompt-injection (`ignore approval`, fake "approved on call") is **blocked** with zero tool calls.

### 3.2 Read vs commit split

| Read / dry-run (never moves money) | Commit (approval + signature + idempotency key required) |
|---|---|
| payroll lookup, leave draft, vendor recon, policy search, slip parse, notice parse, TDS simulate | vendor commit, leave commit |

Approval flow: `/chat` returns `needs_approval` + reasons + signed signatures (15-min expiry) → you `Approve` (+ optional reason) or `Reject` → on approve, PAY-able commits execute once; HOLD invoices (GST mismatch / big breach) stay held for CA review even when approved.

### 3.3 Where the LLM fits

Default mode is **deterministic and rule-based** (that's why evals are reproducible). A model is used only for: (a) mapping your file's columns during import, (b) structuring unstructured text/pdf rows, (c) optional summary polish when `ACCUPAID_LLM_ENHANCE=1`. Backend order: **OpenRouter** (`OPENROUTER_API_KEY`) → **Pollinations.ai free** (no key) → graceful rule-based fallback. `GET /health` shows which backend answered last and how fast. Amounts and IDs never come from the model alone.

### 3.4 Durable ingest

Every upload is a content-addressed **job** (`job_id` = file hash): same file re-uploaded returns the existing report instead of duplicating. Loads commit every 200 rows with natural-key upserts — crash mid-file, re-submit, only the rest loads. Big files can run on a **Temporal** workflow (retries, heartbeats, live progress, cancel); without a server the identical pipeline runs inline automatically.

---

## 4. Getting started

```bat
start.bat    :: seeds demo data, launches API :8000 + console :8501, opens both
stop.bat     :: shuts both down
```

### Console tour (`http://127.0.0.1:8501`)

| Tab | Do this |
|---|---|
| **Chat** | Type Hinglish (or click an example chip). Watch the 7 pipeline stages light up. If approval is needed: read reasons → optional reason → **Approve/Reject**. Commits burst confetti + audit note. |
| **Runs** | Paste any `run_id` → full checkpoint replay timeline (query → route → entities → tool → risk → verdict) + audit CSV download. Recent runs sit in the sidebar. |
| **Ingest** | Slip diff form · notice textarea · **Your file** panel (any `.csv .xlsx .json .pdf .txt`, AI auto-map, preview toggle, PII mode, live job progress + cancel + quarantine/error tables). |
| **Health** | API/db/graph/LLM status, live endpoint cross-check with latencies, release-gate table. |

---

## 5. Everyday tasks

**5.1 Resolve a salary dispute.** Chat: `EMP_042 ki march sallery me 4200 overtime missing hai` → check cited diff → Approve if you agree. Reject with reason if not.

**5.2 Approve from chat apps.** Slack/WhatsApp buttons carry signed links (`ui/chatops.py`): same 15-min expiry, same idempotency — double-taps are safe no-ops.

**5.3 Load your data.** Ingest tab → Your file → pick table (or auto) → leave mapping blank for AI map → **Preview** → fix flagged rows → **Load**. Track via `job_id` (`GET /ingest/jobs/{id}`). Rules: IDs auto-shape, months accept `2026-03`/`03/2026`/`Mar 2026`, amounts tolerate `₹`/commas.

**5.4 Check a salary slip.** Ingest → slip form → red rows = diffs over ₹500 vs payroll.

**5.5 Triage a GST notice.** Ingest → paste notice → demand/due/section/invoices + HOLD/PAY proposal. Over ₹10,000 demand → HOLD → needs your approval.

**5.6 Prove it to auditors.** Runs tab → any `run_id` → Download audit CSV (query, route, entities, tool, risk, verdict, cites, status). Nothing commits without `human_verdict=approve` — show them the zero in the gates table.

---

## 6. Troubleshooting

| Symptom | Cause → fix |
|---|---|
| `GET /health` or `/` 404 | Old server running — `stop.bat`, `start.bat` (endpoints added in PR #11) |
| `OPTIONS … 405` in logs | Old server; CORS added in PR #18 — restart |
| `GET /v1/models` 404 | Expected: that's an OpenAI-protocol probe; our API is custom REST (`GET /` lists it) |
| Port already in use | `stop.bat`, or kill listeners on :8000/:8501 |
| Approval fails "expired" | Links live 15 min — ask again for a fresh signature |
| Approved vendor stays "held" | By design: GST mismatch/amount breach needs CA review, approval doesn't override HOLD |
| Upload "too large / too many rows" | Caps 25MB / 100k rows (env-overridable) — split the file |
| "Unstructured text needs a model" | Set `OPENROUTER_API_KEY` (or use network for free fallback), else send csv/xlsx/json |
| `pip install` conflicts | Always install from pinned `requirements.txt`, never latest streamlit (breaks fastapi) |
| Pages site stale | GitHub Pages deploys from `/docs` on `main` — allow a minute after merge |

## 7. FAQ

**Is my data sent anywhere?** No. Default runs are local SQLite + optional free-tier LLM calls (only file-mapping, text structuring, or opt-in summary polish). No analytics, no trackers.
**Can two people approve the same run?** Yes safely — first approval commits, the rest hit the idempotency ledger (`deduped: true`).
**What if the server crashes mid-upload?** Re-upload the same file: finished 200-row chunks survived, upserts skip what's loaded, the same `job_id` finishes.
**How do I wipe demo data?** Delete `accupaid.db` (+ `checkpoints.db`) and re-run `start.bat` — fresh seed.
**Where do I request a pilot?** The form on the marketing site (delivered to the team inbox).
