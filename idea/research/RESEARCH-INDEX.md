# Research Index — AccuPaid anti-hallucination stack (39 papers, local PDFs in this folder)

File naming: `<arxiv-id>.pdf`. Start with Attention Is All You Need (1706.03762) and read down the stack in order.

## Foundations (why the model behaves this way)
- 1706.03762 Attention Is All You Need: transformers, self-attention. Root of everything below.
- 1810.04805 BERT: bidirectional encoders, basis of embedding retrieval.
- 1908.10084 Sentence-BERT: sentence embeddings. Why e5 multilingual embeddings work for Hinglish RAG.
- 2005.14165 GPT-3: few-shot behavior, also why raw LLMs hallucinate amounts with confidence.
- 2203.02155 InstructGPT: RLHF alignment. Follows instructions but still invents entities.
- 2205.14135 FlashAttention: exact attention in linear memory. Relevant to context-window budgeting for Hindi 3x token fertility.

## Retrieval (ground before you generate)
- 2004.04906 DPR: dense passage retrieval training. Basis of Qdrant chunk retrieval.
- 2004.12832 ColBERT: late-interaction retrieval. Upgrade path if e5 recall fails on Romanized Hindi.
- 2005.11401 RAG: retrieve-then-generate. Core AccuPaid pattern, policy chunks cited in answers.
- 2212.10496 HyDE: hypothetical-document retrieval for vague queries. Use when Hinglish query has no keyword overlap.
- 2307.03172 Lost in the Middle: models ignore mid-context. Reason for the 1800-token doc cap and putting the best chunk first and last.
- 2310.11511 Self-RAG: model decides when to retrieve and critiques its own passages. Upgrade for fetch_docs node.
- 2401.15884 CRAG: grade retrieved docs, rewrite query or fall back on low grade. Direct template for risk_gate retrieval grading.
- 2305.06983 FLARE: retrieve mid-generation when confidence drops. Future upgrade for long auditor summaries.

## Tool use and structure (never let the model free-write money)
- 2210.03629 ReAct: interleaved reasoning plus tool acts. Template for execute_tool node traces.
- 2302.04761 Toolformer: self-supervised tool-use learning. Justification for tool-call retry training data from dispute corpus.
- 2305.15334 Gorilla: API-call generation and hallucination evaluation. Precedent for Pydantic-gated MCP calls.
- 2304.08354 ToolLLM: large-scale tool learning. Reference for scaling past 8 tools.
- 2305.10601 Tree of Thoughts: search over reasoning paths. Optional for high-risk vendor recon: sample 3 recon hypotheses, keep the majority.

## Verification loops (recheck before commit — the heart of AccuPaid)
- 2201.11903 Chain-of-Thought: stepwise reasoning. Required in draft_action, but never trusted alone.
- 2309.11495 Chain-of-Verification: plan verification questions, answer independently, revise. Implement as verify_node between execute_tool and risk_gate.
- 2210.08726 RARR: research and revise model claims against retrieved evidence. Template for slip-parse diff revision.
- 2305.11738 CRITIC: self-correct with tool-interactive critiquing. verify_node calls payroll_lookup again to critique draft amounts.
- 2303.17651 Self-Refine: iterative feedback refinement, capped iterations. Cap verify loops at 2, then escalate to human.
- 2203.11366 Reflexion: verbal reinforcement from trial history. Store rejected drafts per tenant to avoid repeating bad extractions.
- 2305.20050 Lets Verify Step by Step: process supervision beats outcome supervision. Supervise entity extraction steps, not just final answers.
- 2305.14325 Multiagent Debate: agents debate to improve factuality. Optional high-value path: recon agent vs auditor agent, human judges ties.
- 2406.04692 Mixture-of-Agents: aggregated proposer outputs improve quality. Cheap upgrade: 2 proposers for entity extraction, keep agreement.

## Factuality eval (how the harness scores truth)
- 2303.08896 SelfCheckGPT: zero-resource hallucination detection via response consistency. Sample amounts extraction 3x, flag disagreement.
- 2305.14251 FActScore: atomic-fact precision scoring. Score policy answers per atomic claim with citation.
- 2305.14627 ALCE: text generation with citations. Citation format standard for format_response.
- 2309.03883 DoLa: contrastive layer decoding reduces factual errors without retrieval. Cheap decoding upgrade for entity extraction calls.
- 2203.11171 Self-Consistency: majority over reasoning paths. Use for date disambiguation (03/04 trap).
- 2309.15217 RAGAS: automated RAG eval including faithfulness and answer relevancy. Adopt faithfulness metric in harness.py.
- 2203.16634 G-Eval: LLM-as-judge with chain-of-thought. Second judge for ambiguous cases only, never for amounts.
- 2311.05232 Hallucination Survey: taxonomy of causes and mitigations. Onboarding read for anyone touching prompts.
- 2212.08073 Constitutional AI: self-critique against principles. Source of the never-commit-without-approval constitution string.
- 2305.18290 DPO: direct preference optimization. Future fine-tune of extractor on approved vs rejected drafts.
- 2310.03714 DSPy: compile prompts against metrics. Optimization path for normalize plus route prompts once harness is green.

## Application order for the build
1. Ship with: RAG, ReAct traces, CoVe verify_node capped at 2, Pydantic gates, SelfCheckGPT 3x on amounts, FActScore-style atomic checks, RAGAS faithfulness, Lost-in-the-Middle caps.
2. Add when green: Self-RAG, CRAG grading, HyDE fallback, Reflexion memory, debate path for invoices over threshold.
3. Later: DPO fine-tune, DSPy prompt compilation, FLARE long-form.
