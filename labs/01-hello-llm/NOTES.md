# Lab 01 notes: hello-llm

**Question.** Can one client talk to every provider, and what do tokens, latency, and cost look like for the same prompt?

**Setup.** `uv run main.py`. One `OpenAI` client; only `base_url`, `api_key`, `model` change per provider. Keys from the workspace `.env` via `pydantic-settings`.

**Run 1 (2026-09-05)**

| Provider | Model | Tokens in/out | Latency | Cost (paid rates) | Note |
|---|---|---|---|---|---|
| Gemini | gemini-3.5-flash-lite | 18 / 65 | 32.5 s | $0.000168 | Suspiciously slow first call; re-measure |
| Groq | openai/gpt-oss-20b | 88 / 200 | 1.4-2.0 s | $0.000067 | Hit max_tokens=200 (truncated) |
| OpenRouter | minimax/minimax-m2.7:free | 58 / 200 | 5.7 s | $0 | Empty content: reasoning model spent the whole budget thinking. Two other free models 429'd upstream |
| Ollama | qwen3:1.7b | - | - | $0 | Not installed yet |

**Learned**
- "OpenAI-compatible" gets you connectivity, not parity: the same prompt is 18 tokens on Gemini and 88 on Groq (different tokenizers plus hidden system tokens), retired models still appear in `/models`, and reasoning models consume `max_tokens` invisibly.
- Cost is dominated by output price and output length, not input. Cap `max_tokens` deliberately and account for reasoning tokens.
- Free tiers need fallbacks: keep a candidate list and treat 429 as "try the next one", never as a crash.

**Open questions for lab 02**
- Is Gemini free-tier latency consistently that high, or was it a cold first call? Measure 10 calls.
- How much of the token-count difference is the tokenizer vs injected system prompt? Compare with a local tokenizer.
