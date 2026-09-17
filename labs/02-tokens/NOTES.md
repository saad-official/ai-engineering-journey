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

> Drafted by the `pm` agent on 2026-09-17 at Saad's request. These are not yet Saad's own
> words - read, correct, and replace anything you would have put differently. Anything you
> rewrite yourself, delete this line for.

**The 18-vs-88 gap was the wrapper, not the vocabulary.** The intuitive answer assumed the two
providers cut the same string into different numbers of pieces, but on `prose-en` Gemini's own
`countTokens` returned exactly the local o200k number (81 vs 81), and the whole lab 01 gap
reproduced as arithmetic on a 17-token prompt: 17+1=18 and 17+71=88, exact on both providers.
The tokenizer explanation would have been the right one if the comparison had been between
*bare-string* counts on content the vocabularies actually disagree about - pretty JSON is +43
and URLs +28 on Gemini vs o200k - which is to say vocabulary dominates on long
punctuation-dense payloads and is irrelevant on a 17-token English sentence.

**A constant overhead is a tax on call count, not on prompt size.** +71 on every one of the six
texts means the overhead as a percentage is entirely determined by how small the prompt is: 418%
on the 17-token lab 01 prompt, 33% on the 216-token TypeScript sample, ~0.35% on a 20k-token one.
So N small calls pay 71N tokens of scaffolding and one batched call with N items inside pays 71
once - which makes "one call per commit" an expensive architecture before a single word of the
prompt is written.

**Gemini's vocabulary is tuned for natural language and pays for machine text.** It beats o200k
on Urdu (119 vs 129, -10) and loses on pretty JSON (+43), URLs (+28) and TypeScript (+20). What
I do with that: refuse to apply a single correction factor to a local estimate, and carry a
per-content-type margin instead - noting that diffs and JSON, the two things Changelog Forge
actually sends, are exactly where the local number is least trustworthy.

**Minifying JSON is a free win, within its scope.** `json-min` and `json-pretty` are
`json.dumps` of the same Python object - identical meaning, +52% tokens locally (130 -> 198) and
+66% on Gemini (145 -> 241). It costs one `separators=(",", ":")` argument and nothing in
quality, so yes. The limit is that it only applies to payloads I construct; whitespace inside
text a user or a commit message wrote is not mine to strip.

**Budget against `usage.prompt_tokens`, never the local count.** It is the only number that
includes the chat template, and it is the number that is billed and rate-limited. The local
count's error is both per-provider and per-content-type - 0 on English prose, +43 on pretty
JSON, and blind to the +71 wrapper entirely - so it is a free lower bound for a pre-flight guard
with a measured margin, and never the budget itself.

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
