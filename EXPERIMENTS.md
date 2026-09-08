# Experiments Log

Every lab and spike gets a row. Short, factual, with numbers. Longer write-ups live in `experiments/<name>/README.md` or `labs/<nn>-<name>/NOTES.md`.

Format: date | id | question | setup | result (numbers) | conclusion / decision | link.

| Date | ID | Question | Setup | Result | Conclusion | Link |
|---|---|---|---|---|---|---|
| 2026-09-05 | exp-000 | Baseline: what does this machine and budget allow? | i7-8650U 4c/8t, 16 GB RAM, MX130 2 GB (unusable), ~22 GB free per drive, Python 3.14 system, Docker, Node 20 | See `TECHNOLOGY_STACK.md` for provider/local-model decisions | Cloud free tiers for chat; local for embeddings and small-model experiments; keep model set under 8 GB on G: | `TECHNOLOGY_STACK.md` |
| 2026-09-05 | exp-001 | Same prompt via one OpenAI-compatible client against every provider: do the keys work, what do tokens/latency/cost look like? | `labs/01-hello-llm`, 1 prompt, max_tokens=200, temp 0.2 | Gemini 3.5-flash-lite: 18 in / 65 out, 32.5 s (!), $0.000168 at paid rates. Groq gpt-oss-20b: 88 in / 200 out, 1.4-2.0 s, $0.000067. OpenRouter: 2 of 4 free models 429'd upstream; minimax-m2.7:free answered in 5.7 s but returned empty content with 200 completion tokens (reasoning model spent the budget on hidden thinking). gemini-2.5-flash-lite returns "no longer available to new users". Ollama qwen3:1.7b (run 2, CPU only): 27 in / 200 out, 15.6 s (~13 tok/s). Gemini run 2: 4.6 s, so run 1 was a cold start. | Keys valid; local inference works at the predicted speed. Free tiers are usable but uneven: Groq is the fast lane; Gemini free had a long first-call latency (re-measure over 10 calls in lab 02); OpenRouter free needs a fallback list and a reasoning-aware max_tokens. Same prompt costs 2.5x more on Gemini 3.5-flash-lite than Groq gpt-oss-20b because its input tokenizer is more efficient but output is priced 8x higher. **Amended 2026-09-08 after exp-002:** both open questions are now closed with numbers. Gemini's steady state is 0.81 s median / 0.84 s p90 over 10 sequential calls (32.5 s was a cold start, confirmed). And the 18-vs-88 input gap was **not** tokenizer efficiency at all: it is a constant +71-token chat template on Groq vs +1 on Gemini. The prompt is 17 tokens locally, and 17+1=18 / 17+71=88 reproduces both reported numbers exactly. | `labs/01-hello-llm/main.py` |
| 2026-09-08 | exp-002 | How many tokens is a text really, and why do local counts, a provider's own counter, and the billed number all disagree? | `labs/02-tokens`, 6 synthetic texts (EN prose, the same meaning in Urdu, TypeScript, one JSON object minified and pretty-printed, a URL block); 3 numbers each: tiktoken `o200k_base`, Gemini `countTokens`, and `usage.prompt_tokens` from Gemini + Groq | Density varies 1.7x by content type: EN prose 5.15 chars/token vs Urdu 3.07 and URLs 3.08. Urdu needs **+59% tokens for the same sentence** (129 vs 81) with fewer characters. Pretty-printing identical JSON costs **+52% locally, +66% on Gemini** (130->198 local, 145->241 Gemini). Chat-template overhead is **constant, not proportional**: Groq +71 tokens on all six texts, Gemini +1. Gemini's vocabulary beats o200k on Urdu (-10) and loses badly on pretty JSON (+43) and URLs (+28). Gemini latency: median 0.81 s, p90 0.84 s, first call 1.88 s. `max_tokens=16` -> `finish_reason='length'` + truncated JSON + `JSONDecodeError`. | Budget against `usage.prompt_tokens`, never the local estimate: local is a free lower bound whose error is per-provider and per-content-type. Minify JSON before sending (free 34% cut). A constant wrapper means short prompts are proportionally far more expensive than they look - ~400% overhead on a 17-token prompt, ~0.3% on a 20k one, which is an argument for batching. Non-Latin scripts carry a permanent ~1.6x cost and context penalty. Always check `finish_reason` before parsing. | `labs/02-tokens/NOTES.md` |

## Planned experiments (become rows when run)

- exp-001 hello-llm: same prompt, cloud primary vs cloud secondary vs local; tokens, latency, cost.
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
