# Tokens and Context Windows

**Status:** understood (measured in exp-002; re-check when Changelog Forge applies it)
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
guess. Measured in exp-002 with `o200k_base`: English prose 5.15 chars/token, TypeScript 4.03,
minified JSON 3.44, pretty JSON 3.29, URLs 3.08, Urdu 3.07. A 1.7x spread on the *same* rule of
thumb, so "characters ÷ 4" under-counts a JSON payload by ~20% and Urdu by ~40%.

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

### Measured, exp-002 (`labs/02-tokens`, 2026-09-05)

Three numbers per text, because two would not separate the two causes. `local` is `tiktoken`
`o200k_base` on the bare string; `gem:count` is Gemini's own `countTokens` on the *same bare string*
(so `gem:count − local` is purely a **vocabulary** difference); `gem:usage` / `groq:usage` are
`usage.prompt_tokens` from a real chat call (so `usage − count` is purely the **chat template**).

| text | local | chars/tok | gem:count | vocab | gem:usage | wrapper | groq:usage | vs local |
|---|---|---|---|---|---|---|---|---|
| prose-en | 81 | 5.15 | 81 | +0 | 82 | +1 | 152 | **+71** |
| prose-ur | 129 | 3.07 | 119 | **−10** | 120 | +1 | 200 | **+71** |
| code-ts | 216 | 4.03 | 236 | +20 | 237 | +1 | 287 | **+71** |
| json-min | 130 | 3.44 | 145 | +15 | 146 | +1 | 201 | **+71** |
| json-pretty | 198 | 3.29 | 241 | **+43** | 242 | +1 | 269 | **+71** |
| urls | 127 | 3.08 | 155 | +28 | 156 | +1 | 198 | **+71** |

**1. The 18-vs-88 gap from exp-001 was the wrapper, not the vocabulary.** The lab-01 prompt is 17
tokens locally. 17 + 1 = 18 (Gemini reported 18); 17 + 71 = 88 (Groq reported 88). Exact, both
providers. gpt-oss-20b uses the Harmony chat format, which injects a fixed system block (knowledge
cutoff, current date, reasoning effort, channel instructions) before your text; Gemini's
OpenAI-compatible layer adds essentially nothing. The intuitive answer — "different tokenizers" —
was ~0% of the explanation here.

**2. The wrapper is constant, not proportional.** +71 on all six texts, from 81 to 216 local tokens.
So wrapper overhead as a *percentage* is 418% on a 17-token prompt, 33% on a 216-token one, and
~0.35% on a 20k-token one. Constant overhead is an argument for batching: N small calls pay 71N,
one call with N items inside pays 71.

**3. Vocabulary differences are content-specific and can go either way.** Gemini beats o200k on
Urdu (−10) and loses on pretty JSON (+43), URLs (+28) and TypeScript (+20). A single "local estimate
is ~10% low" correction factor would be wrong in both directions. The error is per-provider *and*
per-content-type, which is why the local count is only ever a free lower bound.

**4. Formatting is a free cost lever.** `json-min` and `json-pretty` are `json.dumps` of the *same*
Python object. Identical meaning, +52% tokens locally and +66% on Gemini. Minifying JSON before it
goes into a prompt is a pure win with zero quality cost.

**5. Non-Latin scripts carry a permanent tax.** The Urdu sample has *fewer* characters than the
English one (396 vs 417) and costs 59% more tokens (129 vs 81). Same feature, higher cost and
smaller effective context, for those users specifically.

**6. Fewer tokens ≠ cheaper.** From exp-001, blended cost per million: Gemini $0.000168 / 83 ≈
**$2.02/M**; Groq $0.000067 / 288 ≈ **$0.23/M**. Groq used 3.5x more tokens and still cost 2.5x
less — unit price dominated token count. Cost = tokens × rate; optimise the term with more leverage.

### Latency and truncation

Gemini 3.5-flash-lite, 10 sequential calls: min 0.66 s, **median 0.81 s, p90 0.84 s**, max 1.88 s
(the first call). exp-001's 32.5 s was a cold start, confirmed — one sample is not data.

`max_tokens=16` on a JSON-producing prompt returned `finish_reason='length'`, content
`'{\n  "version": "1.0.0'`, usage 32 in / 12 out, and a `JSONDecodeError`. HTTP 200. The failure
looks like a model-quality problem and is really a budget problem.

## Implementation

`labs/01-hello-llm/main.py` — first usage numbers (exp-001).

`labs/02-tokens/` (exp-002) — the measurement above. Key design decisions:

- **Three numbers per text, not two.** Two numbers give you a gap; three give you two subtractions,
  each isolating one cause. `countTokens` exists precisely because it is the same tokenizer without
  the chat wrapper — it is the control variable.
- **A paired sample** (`JSON_MIN` / `JSON_PRETTY` from one Python object) isolates formatting with
  meaning held constant.
- `prompt_tokens()` uses `max_tokens=1`: `usage` is reported regardless of output length, so the
  expensive half of the call is reduced to one token.
- Provider counts are cached to `.cache/<sha1>.json` keyed on `(kind, provider, model, text)`, so
  re-running to fix a print statement burns no free-tier quota.
- `o200k_base` is deliberately the *wrong* tokenizer for both providers. There is no public local
  tokenizer for Gemini, so the honest move is to use a proxy and **measure its error** rather than
  assume it away.

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
  discovering the limit as a 400 from the provider. Use a local count as a *lower bound* with a
  measured per-provider safety margin (exp-002: o200k under-counted Gemini by up to 22% on pretty
  JSON), never as the budget itself.
- **Normalise payloads before they enter a prompt.** Minify JSON, strip redundant whitespace, drop
  fields the model does not need. exp-002: 34% off, zero quality cost.
- **Constant wrapper overhead changes batching maths.** If every call carries a fixed +71 tokens,
  many tiny calls are proportionally far more expensive than one batched call. Measure the wrapper
  per provider/model before designing a per-item fan-out.
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
   Two independent causes: different tokenizer vocabularies, and provider-side chat templates /
   system scaffolding prepended to your messages. To tell them apart you need a bare-string count
   from the provider's own tokenizer as a control. Measured (exp-002): 17-token prompt → 18 on
   Gemini, 88 on Groq gpt-oss-20b; the gap was a constant +71-token Harmony chat template and
   effectively zero vocabulary difference.
3. *How would you design an experiment to attribute that gap?*
   Three numbers per input: local tokenizer, the provider's bare-string count endpoint
   (`countTokens`), and `usage.prompt_tokens` from a real call. Subtraction 1 isolates vocabulary,
   subtraction 2 isolates the template. Vary content type (prose, code, JSON, non-Latin, URLs) so
   you can tell constant overhead from proportional overhead, and hold meaning constant across a
   paired sample (same object minified vs pretty) to isolate formatting.
4. *Is chat-template overhead constant or proportional, and why does it matter?*
   Constant per call in the simple case (+71 on every text, exp-002). That makes small prompts
   proportionally far more expensive — 418% overhead on a 17-token prompt — which is a direct
   argument for batching many small items into one call rather than fanning out.
5. *A model has a 1M-token context window. Can it write a 1M-token answer?*
   No. Max output is a separate, much smaller limit, and input + reasoning + output share one
   window.
6. *Why do output tokens cost more than input tokens?*
   Prefill is parallelised across the prompt; decode is serial — one full forward pass per output
   token. Output consumes far more GPU time per token.
7. *How do you estimate the cost of a feature before building it?*
   Estimate tokens per call (measured with the model's tokenizer on realistic input, not English
   prose averages), split input/output, multiply by published rates, multiply by expected calls per
   user action, and add a margin for retries and reasoning tokens.
8. *You get a 200 OK with empty content and 200 completion tokens billed. Diagnose it.*
   A reasoning model spent the whole `max_tokens` budget on hidden reasoning tokens before emitting
   any visible content. Raise the budget, lower reasoning effort, or use a non-reasoning model.

## Project application

**Changelog Forge** (Phase 1). A 400-commit diff will not fit any context window, which forces
chunk-and-merge (map-reduce), a token-budget guard before every call, per-run cost logging, and
model routing (cheap model to classify commits, better model for prose). The whole project is an
exercise in spending tokens deliberately. exp-002 gives it four concrete rules: diffs and JSON are
the two content types where the local estimate is *least* trustworthy (+20 and +43 on Gemini), so
carry a per-content-type margin; minify every JSON payload; batch commit classification rather than
one call per commit, because the wrapper is constant; and check `finish_reason` before every
`json.loads` in the map step.

## Limits of what exp-002 proves

Recorded so the numbers are not over-trusted later:

- **One run, one day.** No variance across runs; providers change chat templates and models silently.
- **One model per provider.** The +71 may be Harmony-format-specific (gpt-oss) rather than
  Groq-specific. Untested.
- **Synthetic texts**, not real commit diffs or real user input.
- **`o200k_base` is a proxy**, not Gemini's or gpt-oss's real tokenizer. The "vocab" column is
  "difference from o200k", not "Gemini's tokenizer quality" in the abstract.
- **The wrapper was measured for a single bare user message** — no system prompt, no assistant
  history, no tool schemas. Whether it stays constant once those exist is the open question that
  lab 04 (tool calling) answers.
- **`max_tokens=1`** may itself change what a reasoning model reports; the numbers are input-side
  only and say nothing about reasoning-token accounting.

## References

- `EXPERIMENTS.md` exp-001, exp-002 (2026-09-05) — own measurements.
- `labs/02-tokens/NOTES.md` — full run output.
- Provider pricing pages — re-verify at each use; rates in this note are as logged in exp-001.
