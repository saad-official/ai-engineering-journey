# Lab 03 notes: generation parameters

**Question.** What does `temperature` actually do to the output, how much does it change
in practice, and is `temperature=0` deterministic? Lab 02 measured what a prompt *costs*;
this one measures what the sampling knobs *do*. The roadmap (Phase 1 interview list) names
"why temperature 0 does not guarantee determinism" explicitly, so the point of the lab is
to have a measured answer rather than a repeated claim.

**Prediction, written before the run** (per the week plan, R5 — if this turns out wrong,
leave it wrong and say so, a prediction edited after the fact teaches nothing):

- temp 0 on the creative prompt: 5 identical outputs, or 4 identical and 1 divergent.
- temp 1.2 on the creative prompt: 5 distinct outputs, low similarity.
- the factual prompt: 1 distinct output at **every** temperature, including 1.2.
- `seed` at high temperature: will not fully pin the output.

**Setup.** `uv run main.py` (add `--dry-run` first to see the call plan). Provider is
**Groq** `openai/gpt-oss-20b`, not the workspace's primary Gemini: this is ~45 sequential
calls and Groq answers in ~1 s (lab 02 §C). `--provider gemini` exists for a cross-provider
spot check. Two prompts, both synthetic and public (free-tier prompts train the provider's
models — TECHNOLOGY_STACK.md §1), chosen so that the *pair* is the experiment:

| Measurement | What it is | What it isolates |
|---|---|---|
| `creative` prompt | invent a tool name + tagline, one line | a **flat** next-token distribution — many plausible continuations, so there is something for temperature to reshape |
| `factual` prompt | which HTTP code means "gone permanently", digits only | a **spiky** distribution — flattening a tall spike still leaves a spike. Isolates *how much of "temperature causes variance" is really the prompt* |
| temp 0.0 / 0.7 / 1.2 | same prompt, N samples each | the effect of dividing the logits before the softmax, with the prompt held constant |
| distinct / N | byte-identical groups among comparable runs | the coarse, unarguable signal: did it repeat, yes or no |
| mean pairwise similarity | mean `difflib.SequenceMatcher` ratio on lowercased words, over all C(N,2) pairs | *how far apart* the outputs are when they are not identical — distinct-count cannot tell a synonym swap from a completely different answer |
| `seed` at max temperature | fixed seed, sampling at its loosest | whether the provider's `seed` pins the **sampler's RNG** — run at high temp, because at temp 0 there is no random draw for a seed to pin |
| top_p 1.0 vs 0.1 @ temp 1.0 | temperature neutral, nucleus varied | that `top_p` is a **second, different** knob on the same sampling step: temperature reshapes the distribution, top_p truncates it |
| `finish_reason` | checked on every single run | a run cut off at `length` is the token budget talking, not the temperature. Those runs are dropped from every comparison and reported separately |
| `usage` + cost per block | prompt/completion tokens, priced at Groq's paid rate | `gpt-oss-20b` is a reasoning model — the `think` column is hidden chain-of-thought, billed at the output rate and invisible in the text |

**No cache, on purpose.** Lab 02 cached provider responses so re-runs cost no quota. That
would be actively wrong here: a cache keyed on (prompt, temperature) returns the same
stored completion every time and would *manufacture* the determinism the lab is trying to
measure. Re-sampling **is** the experiment. What is written to disk is a transcript under
`runs/<UTC timestamp>-<provider>.json` carrying the timestamp, the provider and the exact
model id — provenance, never replayed. Every printed number is live.

Pacing: `rate_limit()` sleeps **before** each call for only the time still owed since the
previous call started. Lab 02 slept *after* the call, which skipped the sleep on the error
path (a 429 storm is exactly when pacing matters), paid 2 s after the final call, and made
the real spacing `2 s + latency`. Groq free is 30 RPM = one call per 2 s.

---

## Results (run 1, 2026-09-17)

Command: `uv run main.py`
Model as resolved by the provider: `openai/gpt-oss-20b`
Transcript: `runs/20260917T064347-groq.json`

> **Run 0 was thrown away.** The first attempt used `MAX_TOKENS = 256` and produced
> `finish_reason="length"` on 22 of 45 calls: gpt-oss-20b spent 250-254 tokens on hidden
> reasoning before writing a one-line answer, so the visible text never arrived. The
> creative prompt was unmeasurable and every one of its rows was dropped. Raised to 1024
> and re-ran. This is lab 02 section D happening for real, at the cost of a whole run.

### A. Variance

| prompt | temp | distinct/5 | mean sim | mean out tok |
|---|---|---|---|---|
| creative | 0.0 | 1 | 1.000 | 270.4 |
| creative | 0.7 | 5 | 0.260 | 340.0 |
| creative | 1.2 | 5 | 0.155 | 325.2 |
| factual | 0.0 | 1 | 1.000 | 72.0 |
| factual | 0.7 | 1 | 1.000 | 58.6 |
| factual | 1.2 | 1 | 1.000 | 58.2 |

**creative @ temp 0.0** - five runs, one output:
```
MergeLog - Turn merged PRs into changelog.     (x5, byte-identical)
```

**creative @ temp 1.2** - five runs, five outputs:
```
ReleaseNotesCLI - Merged PRs, ready notes.
ReleaseMate - Consolidate PRs into changelogs
MergeLog - Transform PRs to changelog
MergeLog - Summarize merged pull requests
ChangelogCLI - Generate release notes from PRs
```

**factual @ every temperature** - `410`, five times, at 0.0 and 0.7 and 1.2 alike.

### B. The determinism check

5/5 byte-identical at temp 0 on both prompts - reported by the lab as **"NOT OBSERVED TO
DIFFER IN 5 RUNS"**, explicitly not as proof of determinism, and scoped to one provider,
one model, 5 runs, one afternoon.

### C. Seed at the highest temperature

| block | distinct/5 | mean sim |
|---|---|---|
| creative @ 1.2, no seed | 5 | 0.155 |
| creative @ 1.2, seed=42 | 3 | 0.627 |

Seed did **not** pin the output, but it did measurably narrow it (0.155 -> 0.627). Two
pairs collapsed to identical strings, three outputs remained distinct. Best-effort, as
documented: a seed fixes the sampler's RNG, and the sampler is only the last step.

### D. top_p vs temperature

| block | distinct/5 | mean sim |
|---|---|---|
| creative @ temp 1.0, top_p 1.0 | 5 | 0.291 |
| creative @ temp 1.0, top_p 0.1 | 1 | 1.000 |

top_p 0.1 collapsed the output completely - to the *same string* temp 0.0 produced. Two
different mechanisms, one visible result. Temperature makes the tail unlikely; top_p
makes it impossible.

### E. Summary

```
prompt      temp  top_p   seed   n distinct  mean sim  out tok  think  dropped    cost $
----------------------------------------------------------------------------------------
creative     0.0      -      -   5        1     1.000    270.4    250        0  0.000450
creative     0.7      -      -   5        5     0.260    340.0    319        0  0.000554
creative     1.2      -      -   5        5     0.155    325.2    306        0  0.000532
factual      0.0      -      -   5        1     1.000     72.0     62        0  0.000145
factual      0.7      -      -   5        1     1.000     58.6     49        0  0.000125
factual      1.2      -      -   5        1     1.000     58.2     48        0  0.000124
creative     1.2      -     42   5        3     0.627    409.0    390        0  0.000658
creative     1.0    1.0      -   5        5     0.291    299.8    280        0  0.000494
creative     1.0    0.1      -   5        1     1.000    270.8    251        0  0.000450
----------------------------------------------------------------------------------------
TOTAL      45 calls, $0.003532 (free tier: $0 - this is the paid-rate cost)
```

**Hidden reasoning was 84-95% of every output.** creative@0.7: 319 of 340 tokens. The
answer is one line of about 10 words; everything else is thinking you pay output rates
for and never see.

---

## Learned

<!-- Saad's own words. Do not paraphrase the script's output back — the script already
     printed the numbers; this section is what they MEAN. One or two sentences each:

     - Temperature 0: what did it actually do in 5 runs, and what is the strongest claim
       you are entitled to make from that result? If it repeated 5/5, why is "deterministic"
       still the wrong word — name the mechanism, not the slogan.

     - The creative prompt and the factual prompt saw the SAME temperatures and behaved
       differently. So what is temperature really a knob on? Finish this sentence in your
       own words: "temperature does not add randomness, it ___". Then: what does that
       imply about testing an LLM feature by turning the temperature down?

     - Required by W2-T09, two sentences, concrete and from YOUR work (frontend/mobile,
       not a textbook): one thing you would ship at temp 0 and why, and one thing you
       would ship at temp >= 0.7 and why. Name the actual feature.

     - top_p 0.1 and a low temperature both made the output more repetitive, by different
       mechanisms (reshape vs truncate). Describe a case where that difference bites —
       where you would specifically NOT want the low-probability tail deleted outright.
       Then say what you now think of the "temperature 0.7 + top_p 0.9" default you have
       copied off a docs page before.

     - `seed` at high temperature: did it reproduce the output? Given the answer, what is
       the only reliable way to make an LLM call reproducible in a test suite or a cache?

     - The `think` column: a visible one-line answer cost N output tokens, most of them
       hidden reasoning. What does that do to a cost estimate built from the visible text,
       and where does that bite hardest in Changelog Forge? -->

## Open questions for later labs

<!-- Carry at least one forward. Candidates:
     - does the temp-0 result hold on a non-reasoning model, and on Gemini? (one
       `--provider gemini` run would settle it — R1 says it will be slow, budget for it)
     - does structured output (`json_schema`, lab 04) narrow the distribution enough that
       temperature stops mattering? If the schema constrains the grammar, what is left to
       sample?
     - similarity here is surface-level word overlap. Two outputs that mean the same thing
       in different words score low. When does that metric start lying, and what would the
       embedding-based version cost? (Phase 2)
     - `max_tokens`, `stop`, `frequency_penalty`, `presence_penalty` were not touched.
       Which of them belong in `llm-kit`'s surface and which are per-call?
     - reasoning models expose `reasoning_effort` on some providers. Is that a cheaper
       lever than temperature for the same "be more careful" intent? -->
