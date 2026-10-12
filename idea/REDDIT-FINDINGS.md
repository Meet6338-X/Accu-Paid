# Reddit + HN Findings — AccuPaid (2026-10-12, free backends only)

## What was actually fetched (all saved under scraped/)
- reddit-rlangchain-links.json: 12 fresh r/LangChain thread titles plus permalinks via public RSS (single successful fetch before 429).
- reddit-threads-rss.json: interview thread has post plus 2 comments by u/akornato and u/p3rdy, bodies not in RSS. Eval-audit and budget threads returned 0 entries (rate-limited).
- hn-langgraph-evals.json: Show HN agentrial by alepot55, 2026-02-09, pytest-style agent eval with Wilson CI over N runs, step-level failure attribution, LangGraph-tested, 100 trials $0.06.
- hn-mcp-hitl.json: Show HN AgentRQ by mrtnx, 2026-04-30, 6 points 4 comments, supervisor MCP plus isolated workspace MCPs, optional human-in-the-loop, 500+ production tasks over 6 weeks, Apache 2.0.
- scrape_free x3: V2EX 0 hits on all AccuPaid keywords, HN top headlines generic (no HR-agent thread today).
- BLOCKED: Reddit comment bodies. Jina anonymous access to reddit.com blocked until 11:57 UTC, old.reddit 403 network policy, direct search.json 403, RSS 429 after rapid fetches. No comment quotes in this memo. Anything quoted elsewhere without a login backend is invented.

## Title-level signal (titles are real, reads below are inference, not quotes)
1. Interview-projects thread (1x3pv3f): job seekers explicitly ask for real-world Python backend plus AI projects that stand out. AccuPaid read: gated execution plus eval harness plus approval queue is exactly the portfolio shape being requested. Ship the eval table, not the chatbot GIF.
2. Eval-audit WTP thread (1x38mpr): someone is testing whether teams pay for independent RAG/agent eval audits. AccuPaid read: direct validation of the WTP question in ideas/AccuPaid.md. Watch that thread with login before pricing the CA-partner tier.
3. Budget-mid-run thread (1x3lkzn): operators hit cost walls mid-run. AccuPaid read: P95 latency plus token caps plus free-tier fallback design is a lived pain, keep the 3500-token gate.
4. RAG-regression thread (1x3j7a3): fear of shipping retrieval changes that silently drop evidence. AccuPaid read: worst-slice harness plus citation-rate metric answers this directly. Demo the before/after evidence table.
5. Red-teamer thread: 81% scorer-reply loss on one setup, cheapest scan $0.14. AccuPaid read: adversarial tail cases plus injection tests belong in the 12 adversarial slots of dataset.jsonl.
6. 144-LLMOps-tools thread: LangSmith self-hosted alternatives in demand. AccuPaid read: keep LangSmith but abstract the tracer interface so a pilot can swap backends.
7. E-commerce agent thread (1x2jk3n): same autonomous-workflow-plus-architecture ask as AccuPaid in a different vertical. Pattern repeats across verticals.
8. HN agentrial: one run tells you nothing, run N times with confidence intervals. AccuPaid read: run each tail case 5x in harness.py and report Wilson CI, not point pass rates. Aligns with Sarvam tail thinking.
9. HN AgentRQ: supervisor MCP plus isolated workspaces plus optional HITL survived 500 production tasks. AccuPaid read: independent corroboration of the read-vs-commit split plus interrupt approval architecture.

## Actions for AccuPaid
- Revisit with login backend: pull bodies of 1x3pv3f, 1x38mpr, 1x3lkzn, 1x3j7a3. Bodies change everything; titles only shape the questions.
- Adopt Wilson-CI-over-N-runs in evals/harness.py per agentrial.
- Keep tracer interface swappable per 144-tools demand.
- No market stats may cite this memo as anything above anecdote (evidence level 6).
