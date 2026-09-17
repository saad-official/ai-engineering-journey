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

> Drafted by the `pm` agent on 2026-09-17 at Saad's request. These are not yet Saad's own
> words - read, correct, and replace anything you would have put differently. Anything you
> rewrite yourself, delete this line for.

**Temperature 0 repeated 5/5, and that is still not determinism.** On both prompts the five
runs at temp 0.0 were byte-identical (distinct 1/5, similarity 1.000), so the strongest claim I
am entitled to is "not observed to differ in 5 runs, one provider, one model, one afternoon" -
an observation, not a contract. The mechanism is why the word is wrong: temp 0 is greedy
decoding, take the argmax, which only repeats if the logits are bit-for-bit identical, and on
shared dynamically-batched inference they are not - float addition is not associative, reduction
order depends on who else is in the batch, and gpt-oss is MoE so routing can shift with batch
composition. A 1e-7 wobble between two near-tied candidates flips the argmax, and from that
token on the completions diverge permanently.

**Temperature is a knob on a distribution, and the prompt owns the distribution.** The same
three temperatures took the creative prompt from 1 distinct / 1.000 to 5 distinct / 0.155, and
moved the factual prompt not at all - 1 distinct / 1.000 at 0.0, 0.7 and 1.2 alike. Temperature
does not add randomness, it decides how much of the model's own uncertainty is allowed to reach
the output. Which means turning the temperature down to make a feature testable proves nothing
until I measure it on the real prompt: on a spiky prompt temp 0 buys me nothing that 1.2 was not
already giving me, and on a flat prompt it does not buy reproducibility either (section B).

**Where I would ship each.** Temp 0 for extracting a structured "what changed in this release"
object from raw release text to render in an in-app What's New screen - the output is parsed and
laid out by the client, so variance there is a rendering bug, not a style choice; temp >= 0.7 for
generating three alternative empty-state or onboarding microcopy lines that a human picks from in
review, because there are many good phrasings and one bland repeated line is the actual failure.
`[assumption - replace with a real feature of yours]`

**Reshape and truncate reach the same place, and only one of them is reversible by the model.**
top_p 0.1 at temp 1.0 collapsed to 1 distinct / 1.000 - the exact string temp 0.0 produced -
while temp 1.0 with top_p 1.0 gave 5 distinct / 0.291. The difference bites when the right answer
lives in the tail: a rare but valid identifier or package name in generated code, a non-Latin
word, an uncommon enum value, an unusual API name. A low temperature makes that token unlikely
and still reachable; a low top_p deletes it from the candidate set entirely and no amount of
context can bring it back. So "temperature 0.7 + top_p 0.9" is now something I read as a copied
default rather than a decision - this run shows top_p alone can dominate the result with
temperature held flat, so setting both means I cannot attribute my own output to either knob.
Pick one, leave the other at its default, and log both.

**A seed narrows, it does not pin.** `seed=42` at temp 1.2 gave 3 distinct in 5 with similarity
0.627, against 5 distinct / 0.155 unseeded - a measurable narrowing and not a reproduction,
because the seed fixes the sampler's RNG and the sampler is only the last step. The only reliable
way to make an LLM call reproducible in a test or a cache is to stop re-deriving it: record the
output once as a fixture or a cache entry, replay that, and assert properties (schema parses,
required fields present, values in range) rather than strings.

**The invisible tokens are most of the bill.** Hidden reasoning was 84-95% of every output
block - creative@0.7 was 319 of 340 tokens for a one-line, ~10-word answer - so a cost estimate
built from the visible text under-counts the expensive half of the call by roughly 10x on this
model. In Changelog Forge that lands hardest on the map stage: one classification call per commit
group across a 400-commit range, where the visible answer is a single category word but each call
still pays a few hundred invisible output tokens plus lab 02's constant +71 input wrapper. That
is the concrete argument for batching classification into fewer calls and routing it to a
non-reasoning model - and run 0 is the other half of it, where `max_tokens=256` left nothing for
the visible answer on 22 of 45 calls and the whole run measured nothing.

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

> Drafted by the `pm` agent on 2026-09-17 at Saad's request. These are not yet Saad's own
> words - read, correct, and replace anything you would have put differently. Anything you
> rewrite yourself, delete this line for.

Carried forward, in priority order:

1. **Is lab 02's +71 chat-template constant Harmony-specific or Groq-specific?** Still open from
   lab 02. gpt-oss-20b uses the Harmony format; the +71 may belong to that format, not to Groq.
   Settle it by measuring `usage.prompt_tokens` for one fixed string against a second Groq model
   that is not gpt-oss, and against gpt-oss on another host. It matters because the batching
   argument in lab 02 is sized by that constant.
2. **Does the 84-95% reasoning share hold on other models, or is it this one?** Every block here
   was gpt-oss-20b. Measure the same prompts on a non-reasoning model and on a model that exposes
   `reasoning_effort`. This decides directly whether a reasoning model is usable for Changelog
   Forge's high-volume map stage, and it is the single number that would change that design.
3. **Does `seed` behave the same on a non-reasoning model?** Here it narrowed (0.155 -> 0.627) but
   did not pin. A model with no hidden chain of thought has far less generation upstream of the
   sampler to diverge in, so the seed may pin much harder - or reveal that the non-determinism was
   never in the sampler at all. Same protocol: max temperature, 5 runs, seeded vs unseeded.
4. **Does the temp-0 result hold on Gemini?** One `--provider gemini` run settles it. R1 says it
   will be slow; budget for it rather than skipping it, because the determinism claim currently
   rests on one provider.
5. **Does structured output (`json_schema`, lab 04) narrow the distribution enough that
   temperature stops mattering?** If the schema constrains the grammar, what is left to sample?
6. **When does the similarity metric start lying?** `difflib` over words measures surface form, so
   two outputs that mean the same thing in different words score low. The embedding-based version
   is a Phase 2 cost question.
7. **Which of `max_tokens`, `stop`, `frequency_penalty`, `presence_penalty` belong in `llm-kit`'s
   surface and which are per-call?** None were touched here.

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
