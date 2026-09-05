# Tokens and Context Windows

**Status:** draft
**Phase:** 1   **Tags:** [F], llm-fundamentals / cost / context

## Concept

A model never sees characters or words. Text is cut by a **tokenizer** into sub-word pieces
("tokens") drawn from a fixed learned vocabulary (~50k-250k entries), and each piece is replaced by
an integer ID that indexes an embedding table. The **context window** is the maximum number of
tokens that can exist in one forward pass — system prompt + conversation history + tool schemas +
retrieved documents + reasoning tokens + the answer, all sharing one budget. Tokens are also the
unit of billing and the unit of latency, which is why this one concept governs cost, speed,
architecture, and every retrieval decision later.

## Problem

Why does it exist? A neural net multiplies matrices; it needs a finite vocabulary of discrete
symbols. Characters make sequences too long (attention cost grows ~quadratically with length);
whole words make the vocabulary infinite (typos, code identifiers, new words, other languages).
Byte-Pair Encoding is the compromise: common sequences get one token, rare ones get split into
pieces, and *any* input is representable with zero out-of-vocabulary failures.

What breaks without understanding it:
- You budget cost in "words" or "characters" and are wrong by 2-4x on code, JSON, or Urdu.
- You set `max_tokens` too low on a reasoning model and pay full price for an empty response.
- You assume a 1M-token context means you can *produce* 1M tokens.
- You send full chat history every turn and your per-conversation cost grows quadratically.
- You have no principled reason to build RAG, because you do not feel the budget.

## Mental model

**The LLM API is stateless, like HTTP.** The "conversation" is not stored anywhere — every turn you
re-POST the entire message array. The context window is the **max request body size**, and it is
shared with the response. So the mental model is: *re-sending the whole Redux store on every action
instead of a diff, and paying by the byte, with a hard cap on store size.*

**The tokenizer is a compression dictionary, like gzip's.** A specific dictionary belongs to a
specific model family. Gemini's tokenizer, Llama's, and GPT's cut the same string into different
numbers of pieces — the way the same source file produces different bundle sizes under different
bundlers. You never ship JSX to the browser; you ship a compiled bundle. The model never receives
your string; it receives `[9906, 1917, 0]`.

Rules of thumb for English prose: ~4 characters ≈ 1 token, ~0.75 words ≈ 1 token, a page ≈ 500
tokens, this note ≈ 1,500 tokens. These are worthless for code and non-English — measure, do not
guess.

## Architecture

```
your string
  -> tokenizer (model-family-specific BPE vocab)   "tokenization"
  -> [int ids]
  -> embedding table lookup -> vectors -> transformer layers
  -> logits over vocab -> sampler -> one token id -> appended to input
  -> loop until stop token / max_tokens / context full
  -> detokenize -> string

BUDGET (one shared window, e.g. 128k):
[ chat template + system ][ tool schemas ][ history ][ RAG chunks ][ user turn ] | [ reasoning ][ answer ]
 \____________________________ prompt_tokens (billed input) ______________________/ \___ completion_tokens (billed output) ___/
```

Prefill (reading the prompt) is parallel and cheap per token → drives **time to first token**.
Decode (writing the answer) is serial, one token per forward pass → drives **total latency**.
This is why output tokens cost 3-8x more than input tokens everywhere.

## Example

From `EXPERIMENTS.md` exp-001 — same prompt, two providers:

| Provider / model | in | out | latency | cost |
|---|---|---|---|---|
| Gemini 3.5-flash-lite | 18 | 65 | 32.5 s | $0.000168 |
| Groq gpt-oss-20b | 88 | 200 | 1.4-2.0 s | $0.000067 |

Two lessons in one table.

**1. Same prompt, 18 vs 88 input tokens.** Tokenizer differences alone explain maybe ±20%, not 5x.
The rest is the **chat template**: gpt-oss uses the Harmony format, which injects a system block
(knowledge cutoff, current date, reasoning effort, channel instructions) before your text. You are
billed for tokens you never wrote. `prompt_tokens` from the provider is always ≥ your local count.

**2. Fewer tokens ≠ cheaper.** Blended cost per million tokens: Gemini $0.000168 / 83 ≈ **$2.02/M**;
Groq $0.000067 / 288 ≈ **$0.23/M**. Groq used 3.5x more tokens and still cost 2.5x less, because
unit price dominates token count. Cost = tokens × rate; optimise the term with the larger leverage.

## Implementation

`labs/01-hello-llm/main.py` — first usage numbers (exp-001).
Planned: `labs/02-tokens` (exp-002: local tokenizer counts vs provider-reported `usage`).

## Trade-offs

- **Long context vs retrieval.** Stuffing everything in a large window is simpler, but cost and
  latency scale with tokens and accuracy degrades in the middle of long inputs. RAG trades
  engineering complexity for a bounded, relevant prompt. Measure before choosing (exp-011).
- **Verbose vs compact prompts.** Few-shot examples cost tokens on every call, forever. A
  fine-tune or a better instruction may be cheaper at volume.
- **Reasoning models.** Buy accuracy with invisible output tokens. Great for hard tasks, terrible
  for high-volume cheap classification.

## Production considerations

- **Count before you send.** Token-budget guard in the client layer; reject or truncate rather than
  discovering the limit as a 400 from the provider.
- **Reserve headroom** for `max_tokens` (and for reasoning tokens) inside the window; a request
  that fits the input but not the answer is still a failure.
- **Log `usage` on every call** (prompt, completion, reasoning, cached) and derive cost per request
  from a price table in config, not hardcoded.
- **Prompt caching** on stable prefixes (system prompt, tool schemas, long documents) cuts input
  cost substantially — put the stable part first, the variable part last.
- **History management**: sliding window, summarisation, or discard — chat cost grows quadratically
  otherwise.
- **`finish_reason == "length"`** is a silent truncation bug, especially with JSON output. Always
  check it, never trust a parsed body without it.

## Interview questions

1. *What is a token, and why do models use them instead of characters or words?*
   Sub-word unit from a learned BPE vocabulary mapped to an integer ID. Characters make sequences
   too long for quadratic attention; words make the vocabulary unbounded. Sub-words give a fixed
   vocab with no out-of-vocabulary failures.
2. *The same prompt reports different input token counts on two providers. Why?*
   Different tokenizer vocabularies, plus provider-side chat templates and system scaffolding
   prepended to your messages. Provider `prompt_tokens` ≥ your local tokenizer count.
3. *A model has a 1M-token context window. Can it write a 1M-token answer?*
   No. Max output is a separate, much smaller limit, and input + reasoning + output share one
   window.
4. *Why do output tokens cost more than input tokens?*
   Prefill is parallelised across the prompt; decode is serial — one full forward pass per output
   token. Output consumes far more GPU time per token.
5. *How do you estimate the cost of a feature before building it?*
   Estimate tokens per call (measured with the model's tokenizer on realistic input, not English
   prose averages), split input/output, multiply by published rates, multiply by expected calls per
   user action, and add a margin for retries and reasoning tokens.
6. *You get a 200 OK with empty content and 200 completion tokens billed. Diagnose it.*
   A reasoning model spent the whole `max_tokens` budget on hidden reasoning tokens before emitting
   any visible content. Raise the budget, lower reasoning effort, or use a non-reasoning model.

## Project application

**Changelog Forge** (Phase 1). A 400-commit diff will not fit any context window, which forces
chunk-and-merge (map-reduce), a token-budget guard before every call, per-run cost logging, and
model routing (cheap model to classify commits, better model for prose). The whole project is an
exercise in spending tokens deliberately.

## References

- `EXPERIMENTS.md` exp-001 (2026-09-05) — own measurements.
- Provider pricing pages — re-verify at each use; rates in this note are as logged in exp-001.
