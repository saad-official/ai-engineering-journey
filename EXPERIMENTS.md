# Experiments Log

Every lab and spike gets a row. Short, factual, with numbers. Longer write-ups live in `experiments/<name>/README.md` or `labs/<nn>-<name>/NOTES.md`.

Format: date | id | question | setup | result (numbers) | conclusion / decision | link.

| Date | ID | Question | Setup | Result | Conclusion | Link |
|---|---|---|---|---|---|---|
| 2026-09-05 | exp-000 | Baseline: what does this machine and budget allow? | i7-8650U 4c/8t, 16 GB RAM, MX130 2 GB (unusable), ~22 GB free per drive, Python 3.14 system, Docker, Node 20 | See `TECHNOLOGY_STACK.md` for provider/local-model decisions | Cloud free tiers for chat; local for embeddings and small-model experiments; keep model set under 8 GB on G: | `TECHNOLOGY_STACK.md` |
| 2026-09-05 | exp-001 | Same prompt via one OpenAI-compatible client against every provider: do the keys work, what do tokens/latency/cost look like? | `labs/01-hello-llm`, 1 prompt, max_tokens=200, temp 0.2 | Gemini 3.5-flash-lite: 18 in / 65 out, 32.5 s (!), $0.000168 at paid rates. Groq gpt-oss-20b: 88 in / 200 out, 1.4-2.0 s, $0.000067. OpenRouter: 2 of 4 free models 429'd upstream; minimax-m2.7:free answered in 5.7 s but returned empty content with 200 completion tokens (reasoning model spent the budget on hidden thinking). gemini-2.5-flash-lite returns "no longer available to new users". Ollama: not installed yet. | Keys valid. Free tiers are usable but uneven: Groq is the fast lane; Gemini free had a long first-call latency (re-measure over 10 calls in lab 02); OpenRouter free needs a fallback list and a reasoning-aware max_tokens. Same prompt costs 2.5x more on Gemini 3.5-flash-lite than Groq gpt-oss-20b because its input tokenizer is more efficient but output is priced 8x higher. | `labs/01-hello-llm/main.py` |

## Planned experiments (become rows when run)

- exp-001 hello-llm: same prompt, cloud primary vs cloud secondary vs local; tokens, latency, cost.
- exp-002 tokenizer vs provider usage counts.
- exp-003 temperature variance study.
- exp-004 structured output robustness under adversarial input, per provider.
- exp-005 tool-calling behaviour differences across providers and a local model.
- exp-006 map-reduce vs single-shot summary quality on a long document.
- exp-007 chunking strategies vs retrieval hit rate.
- exp-008 pgvector HNSW vs no index latency at 10k rows.
- exp-009 hybrid (RRF) vs vector-only recall@5.
- exp-010 reranker impact on recall@5 and latency on CPU.
- exp-011 RAG vs long-context: quality, latency, cost.
- exp-012 tool description quality vs agent success rate.
- exp-013 plan-execute vs ReAct on the same tasks.
- exp-014 LangGraph vs Pydantic AI vs hand-written loop for the HITL agent.
- exp-015 exact vs semantic cache hit rates and savings.
- exp-016 prompt-injection red-team results before and after defences.
