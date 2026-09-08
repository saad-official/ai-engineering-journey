# Lab 02 notes: tokens

**Question.** How many tokens is a piece of text, and why does the number you count
locally disagree with the number you are billed for? Lab 01 left two open questions:
where the 18-vs-88 token gap came from, and whether Gemini's 32.5 s call was a cold start.

**Setup.** `uv run main.py`. Six synthetic texts of different shapes (English prose, the
same meaning in Urdu, TypeScript, the same JSON object minified and pretty-printed, and a
URL-heavy block). Three numbers per text:

| Number | What it is | What it isolates |
|---|---|---|
| local | `tiktoken` `o200k_base` on the bare string | a free, offline estimate |
| `gem:count` | Gemini's native `countTokens`, bare string | **vocabulary** difference vs local |
| `gem:usage` / `groq:usage` | `usage.prompt_tokens` from a real call | the **chat template** the provider adds |

`gem:count` and `gem:usage` are the same text through the same model; the only difference
is that one goes through the chat wrapper. That subtraction is the whole design of the lab.

Provider counts are cached under `.cache/` so re-runs cost no quota. `--local-only` runs
with no network at all. Calls are 2 s apart (Gemini free-tier RPM is still UNVERIFIED).

---

## Results (run 1, 2026-09-08)

### A. Local counts (`o200k_base`)

| text | chars | words | tokens | chars/tok |
|---|---|---|---|---|
| prose-en | 417 | 71 | 81 | 5.15 |
| prose-ur | 396 | 87 | 129 | 3.07 |
| code-ts | 870 | 93 | 216 | 4.03 |
| json-min | 447 | 17 | 130 | 3.44 |
| json-pretty | 652 | 62 | 198 | 3.29 |
| urls | 391 | 5 | 127 | 3.08 |

### B. Local vs provider-reported

| text | local | gem:count | vocab | gem:usage | wrapper | groq:usage | vs local |
|---|---|---|---|---|---|---|---|
| prose-en | 81 | 81 | +0 | 82 | +1 | 152 | **+71** |
| prose-ur | 129 | 119 | -10 | 120 | +1 | 200 | **+71** |
| code-ts | 216 | 236 | +20 | 237 | +1 | 287 | **+71** |
| json-min | 130 | 145 | +15 | 146 | +1 | 201 | **+71** |
| json-pretty | 198 | 241 | +43 | 242 | +1 | 269 | **+71** |
| urls | 127 | 155 | +28 | 156 | +1 | 198 | **+71** |

### C. Gemini latency, 10 sequential calls

```
n=10  min=0.66s  median=0.81s  mean=0.91s  p90=0.84s  max=1.88s
first call 1.88s vs median of the rest 0.81s
```

### D. Truncation (`max_tokens=16`)

```
finish_reason = 'length'
content       = '{\n  "version": "1.0.0'
usage         = 32 in / 12 out
json.loads    = JSONDecodeError: Unterminated string starting at
```

### The exp-001 gap, closed

The lab 01 prompt was `"In two sentences, explain what a token is in the context of a
language model."` — 17 tokens locally.

| | predicted | exp-001 actually reported |
|---|---|---|
| Gemini | 17 + 1 wrapper = **18** | 18 |
| Groq | 17 + 71 wrapper = **88** | 88 |

Exact, both providers. The 18-vs-88 gap was **~100% chat template and ~0% tokenizer
vocabulary** — the opposite of the intuitive explanation.

---

## Learned

<!-- Saad's own words. Aim at these, one or two sentences each:
     - the 18-vs-88 gap: it was the wrapper, not the vocabulary. Why did the intuitive
       answer (different tokenizers) turn out to be wrong here, and when WOULD it be right?
     - the wrapper column is +71 for Groq on every single text, and +1 for Gemini. What
       does a constant (rather than proportional) overhead mean for short vs long prompts?
     - Gemini's vocab delta is -10 on Urdu but +43 on pretty JSON. What is Gemini's
       tokenizer better and worse at than o200k, and what would you do with that?
     - min-vs-pretty JSON: formatting alone cost +52% locally and +66% on Gemini. Free win?
     - which number do you budget against in production, and why not the local one? -->

## Open questions for later labs

<!-- carry at least one forward. Candidates:
     - is the Groq +71 constant across models, or specific to gpt-oss-20b's Harmony format?
     - does the wrapper grow with a system message and with tool schemas? (lab 04 tools)
     - reasoning tokens: exp-001 saw 200 completion tokens with empty content. Where do
       those show up in usage, and can you budget for them? -->
