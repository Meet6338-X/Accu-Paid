---
slug: AccuPaid
state: Shape # Spark / Signal / Shape / Stress / Spec / Ship / Story / Scale / Pivot-Dead
status: draft # draft -> refined -> pursue / kill / park
created: 2026-10-12
audience: HR ops plus payroll execs at 50-500 person Indian SMEs on Keka/Zoho People, 10+ Hinglish disputes per week
---

# AccuPaid

> Full OS: `../../../templates/master-ideation-OS.md`. Prime Mode rule: every idea outputs state, evidence, confidence, next experiment, kill criteria. Startup lens: this file is the wedge, STARTUP-PLAN is the company.

## Idea Score (0-10 each, multiply — any zero kills it)
- Pain: 9/10, Frequency: 8/10, Urgency: 7/10, WTP: 7/10, Feasibility: 8/10, Novelty: 7/10, Distribution: 6/10, AI Leverage: 9/10
- Total: 9*8*7*7*8*7*6*9 = 10668672
- Confidence: med

## One-liner
AccuPaid helps Indian SME HR/payroll ops resolve Hinglish salary disputes and vendor GST recon by gated tool execution with human approval.

## State
Shape

## Problem
Payroll and vendor queries arrive as code-mixed typos on Slack and WhatsApp. Generic RAG chatbots hallucinate emp_id, dates, and amounts, causing mispayments and GST penalty risk. HR copy-pastes between attendance, payroll sheets, and policy PDFs 15+ hrs per week.

## Target User
HR operator plus payroll exec, 50-500 headcount, Keka or Zoho People, English plus Hinglish workforce, no ML team. Budget owner is founder or HR head. Trigger event is a salary-day dispute spike or GST notice.

## Current Alternatives
Keka/Zoho macros, Excel VLOOKUP recon, CA consultants for GST mismatch, generic GPT wrappers with no tool gates.

## Why Now
Keka Hire AI Engineer Intern JD 2026 asks LangGraph plus MCP plus evals plus FastAPI beyond chatbots. lablab.ai 2026 pattern: Vultr Agent Rush demands sandboxed execution not chat, Band of Agents demands 3-plus collaborating agents, Alpaca demands MCP/CLI plus risk gates. Sarvam playbook rewards tail-eval over aggregate. multilingual-e5 plus FastMCP plus LangSmith make a weekend build feasible.

## Solution
FastAPI gateway with approval queue. LangGraph supervisor with SQLite checkpointer. Nodes: normalize_query, route_query, fetch_docs, execute_tool, risk_gate, human_approval via interrupt, format_response. Qdrant RAG over PF/ESI/TDS/GST docs. payroll-mcp with 4 Pydantic tools: payroll_lookup read-only, leave_apply, vendor_recon dry-run, policy_search. vendor_commit exists but requires human_verdict approve. LangSmith traces every node and tool.

## V2 Features (startup durable set)
1. Voice-note intake: WhatsApp audio plus screenshot OCR via Tesseract, transliterated to Hinglish text with confidence score, low-confidence spans flagged for human confirm.
2. Salary-slip parser: PDF upload extracts gross, TDS, PF, net with table OCR, diffs against payroll_lookup, highlights mismatches over INR 500.
3. Attendance-to-ledger close: biometric CSV import, LOP auto-calc, overtime estimator, draft journal entry with policy cite before approval.
4. TDS and PF estimator: what-if simulator for CTC changes, regime old vs new, shows delta with citations, never commits.
5. GST notice parser: GSTN PDF or text paste extracts demand amount, due date, section, maps to vendor invoices, proposes HOLD or PAY with risk score.
6. Slack and WhatsApp bot: approve or reject with reason from chat using signed buttons, idempotency key per run_id, 15-min expiry.
7. Auditor export: one-click PDF plus CSV of every approved commit with trace_id, tool inputs, policy cites, approver identity.
8. Guardrails: PII redaction in traces, per-tool timeout 25s with 3x retry, per-tenant rate limits, Postgres checkpointer for pilot phase, full offline replay of any run_id.

## Novelty Wedge
Gated execution plus Sarvam-style tail eval as the product: Hinglish typo benchmark, Entity-WER gate, worst-slice release block, dry-run ledger before commit. Competitors sell chat; AccuPaid sells zero-unapproved-commits with audit trail.

## AI Leverage
Hinglish normalization, intent plus entity structured extraction, policy RAG with citations, draft ledger action, retry on tool validation error, summary-buffer for token-fertility control on Hindi 3x token blowup.

## Data Moat
Per-company dispute corpus of query, entities, resolution, approval. Improves retrieval calibration and jargon extractor. GST mismatch patterns compound across vendors. Starts as retrieval moat, becomes calibration moat on win rates.

## Demo Moment
Type `mera march ki salary kam ayi, TDS jyada kata? EMP_042` with typo. Shows normalized query, retrieved TDS chunk, dry-run diff INR 4,200 overtime missing, Approve button, commit plus audit plus LangSmith trace in under 60s.

## Business Model
Wedding-cake startup pricing: pilot free for 1 company up to 100 employees for 30 days, then per-seat INR 199 per HR seat per month plus INR 15 per vendor recon over 200 per month. Annual prepay 2 months free. CA-firm partner tier for GST angle. See STARTUP-PLAN for unit economics watch-items.

## Go-to-Market
First 10 pilots from Meet network plus Keka partner directory plus CA firms. Distribution via 90-sec Hinglish demo video plus LangSmith eval screenshot, not ads. Kill generic HR content; ship dispute-resolution teardowns.

## Key Metrics
North Star: approved commits with zero unapproved money moves. Supporting: Entity-WER tail under 7 percent, worst-slice task completion over 65 percent, approval-to-commit P95 under 8s, HR hours saved per week.

## Market Stats (never invent — source + year required)
- lablab.ai Vultr Agent Rush 2026 requires sandboxed code/browser execution with containment, not chat-only demo. Source: https://lablab.ai/ai-hackathons/vultr-hackathon 2026
- lablab.ai Band of Agents 2026 requires minimum 3 agents collaborating via shared layer for enterprise HR/finance/procurement. Source: https://lablab.ai/ai-hackathons/band-of-agents-hackathon 2026
- lablab.ai Alpaca Trading Agents 2026 requires autonomous agent plus MCP server or CLI plus risk gates plus one-page writeup. Source: https://lablab.ai/ai-hackathons/alpaca-ai-trading-agents-hackathon 2026
- Keka AI Engineer Intern JD 2026 asks LangGraph, Agent Harness, MCP server/client, AI Observability, LLM Evals, FastAPI, RAG over enterprise docs. Source: user-provided JD 2026
- Free scrape proof: scraped/2026-10-12-langgraph-mcp-hr-payroll-agent.json from workflows/scrape_free.py V2EX plus HN RSS, 2026-10-12, copied to this project scraped dir
- TAM/SAM/SOM: to be filled at refine time with sourced reports only. No invented market size in this draft.

## Novelty Score
7/10. Type: technical (Pydantic-gated MCP execution plus tail-eval release gates) + integration (LangGraph HITL plus Qdrant Hinglish RAG plus LangSmith).

## Risks
Hindi token fertility blows context if docs uncapped, strict Pydantic regex rejects real IDs, approval fatigue if risk threshold wrong, Romanized Hindi retrieval poor without transliteration map, salary data in traces needs redaction, incumbents Keka/Zoho bundle a slim version free.

## Kill Criteria
If Entity-WER on 48 tail Hinglish cases exceeds 7 percent after 2 prompt iterations, kill the extractor and pivot to template-first. If worst-slice task completion under 65 percent, kill. If any commit path bypasses human approval in traces, kill ship. If P95 latency over 8s on free-tier LLM, kill scope to read-only lookup. If 3 pilots refuse paid conversion after time-saved proof, kill SaaS and pivot to CA-partner API.

## Next Experiment
Weekend spike: seed SQLite 20 employees plus 60 payroll rows plus 15 invoices, ingest 6 policy PDFs to Qdrant, implement 4 MCP tools, compile LangGraph with interrupt, run 120-case harness with 40 percent tail, record approve-to-commit demo, fill 8-persona panel plus synthesis.
## Ask
Panel reality-check, 2 pilot intros, review of STARTUP-PLAN pricing and moat. Hiring signal first, startup second.
