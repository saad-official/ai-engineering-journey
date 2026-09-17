# Generation Parameters (temperature, top_p, top_k)

**Status:** learning (exp-003 run on 2026-09-17 and its numbers are in `labs/03-params/NOTES.md`; this note is still agent-drafted and not yet in Saad's own words)
**Phase:** 1   **Tags:** [F], llm-fundamentals / sampling / determinism / evals

## Concept

At every single generation step the model outputs one **probability distribution over its entire
vocabulary** (~50k-200k entries) — "given everything so far, how likely is each possible next
token". The model stops there. Something else, the **sampler**, then picks one token from that
distribution, appends it to the input, and the whole forward pass runs again for the next token.
Generation parameters (`temperature`, `top_p`, `top_k`, and friends) configure **the sampler, not
the model**. Same weights, same prompt, same logits — different chooser, different text.

Two things follow that people constantly get wrong:
1. This happens **once per token**, not once per response. A single unlucky token at position 12
   can send the remaining 300 tokens down a completely different path.
2. `temperature=0` selects the *most likely* token, which is not the same as *deterministic
   output*. See "Why temperature 0 is not determinism" below.

## Problem

Why does a sampler exist at all? Because always taking the highest-probability token (greedy
decoding) is a genuinely bad default for open-ended text: it produces bland, repetitive,
loop-prone output, and it collapses a model that *knows* ten good product names into one that can
only ever say the same one. And because different tasks want opposite things from the same model —
extraction wants the single best answer, brainstorming wants a sample from the space of good
answers. One model, one prompt, two jobs, so the choice has to live outside the weights.

What breaks without understanding this:
- You ship a JSON extractor at the provider's default temperature (usually **1.0**, not 0) and get
  intermittent schema failures you cannot reproduce.
- You set `temperature` *and* `top_p` together, and cannot explain your own output distribution.
- You write tests that assert exact output strings; they pass locally and flake in CI forever.
- You run an eval once, see 82%, and treat it as a fact rather than one draw from a distribution.
- You raise temperature to "make it more creative" and get more hallucinated PR numbers, because
  low-probability tokens include both the interesting ones and the wrong ones.

## Mental model

**The model is a ranking function; the sampler is the picker.** Think of autocomplete in an IDE:
the language server returns a ranked candidate list with scores (that is the model — deterministic
given the same input). What happens next is a *policy*: always take the top item, or pick randomly
from the top few. Changing the policy does not change the language server.

**temperature = how much you trust the ranking.**
Softmax with temperature, in one line: `p_i ∝ exp(logit_i / T)`. Dividing by `T` before the
exponential is the whole mechanism.

```
logits:  "sunny" 8.0   "cloudy" 6.0   "purple" 1.0

T = 0.0  ->  [##################################################]  sunny 100%   (argmax, no sampling)
T = 0.7  ->  [#########################################         ]  sunny ~94%, cloudy ~6%, purple ~0%
T = 1.0  ->  [###########################################       ]  sunny ~88%, cloudy ~12%, purple ~0.1%
T = 1.2  ->  [######################################            ]  sunny ~81%, cloudy ~16%, purple ~0.3%
T -> inf ->  [##                                                ]  uniform over the whole vocabulary
```
`T < 1` makes the distribution **peakier** (rich get richer). `T > 1` makes it **flatter**, which
does not just add "creativity" — it lifts the tail, where both the surprising word and the
factually wrong word live. Note that at T=1.2 "purple" is still only ~0.3%; the visible effect of
temperature usually comes from reordering *near-tied* candidates, not from summoning nonsense. That
is exactly why variance is content-dependent (see the experiment design).

**top_p (nucleus sampling) = how many candidates are even allowed in the room.** Sort tokens by
probability descending, walk down accumulating probability, cut the list the moment the cumulative
sum reaches `p`, renormalise, sample from what is left. `top_p=0.9` on a confident step might keep
2 tokens; on an uncertain step it might keep 400. It adapts to the model's own confidence, which is
the reason it beat fixed-size truncation.

**top_k = keep the k highest-probability tokens, full stop.** Same idea, fixed size instead of
adaptive. Mostly superseded by `top_p`; some providers do not even expose it.

**They are two different steps, in order:**

```
logits --[ temperature: reshape ]--> probs --[ top_k / top_p: truncate ]--> candidates --[ sample ]--> token
```

This is why setting both aggressively is usually a mistake: temperature changes the *shape*, which
changes where the cumulative-probability cut lands, so the two knobs interact non-linearly and you
can no longer reason about either. **Convention: pick one, leave the other at its default.** Tune
temperature; leave `top_p=1.0`.

## Architecture

```
prompt tokens
  -> transformer forward pass
  -> LOGITS: one raw score per vocabulary entry        <- the model ends here; deterministic in theory
  -------------------------------------------------- sampler boundary (all params live below)
  -> repetition / presence / frequency penalties       (optional, adjust logits)
  -> logit_bias                                        (optional, force/ban specific tokens)
  -> divide by TEMPERATURE -> softmax -> probabilities
  -> TOP_K truncate (fixed size)  -> TOP_P truncate (cumulative mass) -> renormalise
  -> sample one token (or argmax if T == 0)
  -> append to context, loop for the next token
  -> stop on: stop sequence | EOS token | max_tokens (finish_reason='length')
```

Per-token loop. `seed` (where a provider supports it) fixes the sampler's RNG, so it removes
*sampling* randomness only — not the hardware-level non-determinism below.

## Example

> **Placeholder — fill from the real exp-003 run in `labs/03-params`.**

Design: one open-ended prompt sent at `temperature` 0.0 / 0.7 / 1.2, five runs each, against Groq
`openai/gpt-oss-20b`; measure **distinct output count (1-5)** and **mean pairwise similarity**
across the five. Plus a small `top_p` sweep at fixed temperature, and the same protocol on a
**factual** prompt as a contrast.

| prompt | temp | top_p | distinct/5 | mean pairwise similarity | note |
|---|---|---|---|---|---|
| open-ended | 0.0 | — | TBD | TBD | TBD |
| open-ended | 0.7 | — | TBD | TBD | TBD |
| open-ended | 1.2 | — | TBD | TBD | TBD |
| factual | 0.0 | — | TBD | TBD | TBD |
| factual | 0.7 | — | TBD | TBD | TBD |
| factual | 1.2 | — | TBD | TBD | TBD |
| open-ended | fixed | 0.1 / 0.5 / 1.0 | TBD | TBD | TBD |

### Predictions before running (written 2026-09-17, before any data)

Falsifiable, so the run can prove them wrong. Score each honestly afterwards.

1. **Temperature 0 will not give 5/5 identical outputs on the open-ended prompt.** Expect 2-4
   distinct strings out of 5, with mean pairwise similarity high (> 0.9) but not 1.0 — most runs
   agreeing, a minority diverging at one early token and then staying diverged.
   *Falsified if:* 5/5 byte-identical at T=0 across every repetition.
2. **Variance will be strongly content-dependent.** The factual prompt will show near-zero
   distinct-count growth from 0.0 to 1.2 (probably ≤ 2 distinct, similarity > 0.9 even at 1.2),
   while the open-ended prompt goes to 5/5 distinct at 1.2 with a clearly lower similarity. The gap
   between the two prompts at T=1.2 will be larger than the gap between T=0.0 and T=1.2 on the
   factual prompt.
   *Falsified if:* the factual prompt's variance rises about as much as the open-ended one's.
3. **The jump from 0.0 to 0.7 will be larger than the jump from 0.7 to 1.2.** Measured as the drop
   in mean pairwise similarity: `sim(0.0) − sim(0.7)` > `sim(0.7) − sim(1.2)`. Reasoning: going
   from argmax to *any* sampling is a categorical change; after that the near-ties are already in
   play and 1.2 mostly reweights the same small candidate set.
   *Falsified if:* similarity falls roughly linearly, or falls faster in the upper interval.

Bonus, unscored: `top_p=0.1` at a high temperature will look closer to `temperature=0` than to the
same temperature at `top_p=1.0` — truncation dominating reshaping.

## Implementation

> **Placeholder — link and summarise once `labs/03-params` has run (exp-003).**

Design decisions to record here after the run:
- **Why 5 runs and not 1.** One sample is not data. exp-001's "Gemini takes 32.5 s" was a cold
  start that dissolved at n=10 (median 0.81 s). Sampling variance is exactly the same class of
  mistake: with n=1 you cannot distinguish "this model is deterministic" from "I got lucky once".
  n=5 is the cheapest number that can still show a *range*; it detects gross effects, not subtle
  ones, and the note should say so honestly.
- **Why three temperatures and not two.** Two points can only ever draw a straight line. Three
  points are the minimum that can show whether the response to temperature is linear or not —
  prediction 3 above is only testable because there is a middle point.
- **Why an open-ended prompt AND a factual one.** Variance is a property of the *distribution*, not
  of the temperature alone. A factual prompt ("capital of France") has one token at ~99.9%; flatten
  that distribution and the argmax still wins. Run only the factual prompt and the lab concludes
  "temperature does nothing" — a real, confident, wrong finding. The pair is what makes the result
  attributable.
- **Why measure similarity numerically instead of eyeballing.** Eyeballing 5 outputs gives an
  impression, not a number you can put in a table, compare across temperatures, or re-run after a
  provider changes the model. It also removes the confirmation bias of the person who wrote the
  hypothesis. Same discipline as exp-002: three numbers per text, because subtraction is what
  isolates a cause.

## Why temperature 0 is not determinism

This is the part most engineers get wrong, and it directly contradicts the frontend instinct that
the same input gives the same output.

`temperature=0` means **greedy decoding**: take the argmax of the logits. That removes *sampling*
randomness. It does not remove:

- **Floating-point non-associativity in batched GPU kernels.** `(a+b)+c != a+(b+c)` in float. The
  order in which a reduction (sum, matmul, all-reduce) accumulates depends on kernel launch
  configuration, which depends on **batch shape** — i.e. on who else's requests landed in the same
  batch on shared inference infrastructure. Your logits shift in the last decimal places. Almost
  always harmless; occasionally two near-tied candidates swap places, and argmax picks a different
  token. From there the sequences diverge permanently.
- **MoE routing.** Mixture-of-experts models (gpt-oss-20b included) route each token to a few
  experts, and in some serving implementations routing is affected by batch composition and expert
  capacity limits. Same input, different batch, different expert, different logits.
- **Provider-side model updates behind a stable name.** `gpt-oss-20b` or `gemini-3.5-flash-lite`
  is a pointer, not a version. Quantisation, serving stack, chat template, and system scaffolding
  can all change under you without the string changing. exp-002 already saw a +71-token chat
  template that is entirely provider-side and could change tomorrow.
- **Non-zero floors.** Some APIs clamp `temperature=0` to a small epsilon rather than switching to
  true argmax.

**What this breaks.** In React, `render(props)` is a pure function and snapshot testing works
because of that purity. An LLM call is closer to an integration test against a third-party service
whose implementation changes weekly: even at T=0 you have a *mostly*-stable, not stable, function.

**What to do instead — never assert the exact string.** Assert properties:
- schema validity (Pydantic parse succeeds) and required fields present;
- invariants ("every PR number in the output exists in the input", regex + verification);
- set membership for classification (`category in {feature, fix, breaking, internal}`);
- numeric bounds (length budget, token budget, cost);
- semantic closeness to a reference (embedding similarity) with a threshold, not equality;
- an **LLM judge with a rubric** for prose quality, itself run at low temperature — and remember
  the judge is non-deterministic too, so a judged eval also needs repetition.
- record **pass rate over N runs**, not pass/fail over 1. "9/10 runs produce valid JSON" is the
  honest unit of an LLM test.
- pin the model version string wherever the provider exposes one, and log the model actually
  returned in the response.

## Trade-offs

| Setting | Use when | Cost of getting it wrong |
|---|---|---|
| `temperature` 0-0.2 | extraction, classification, structured output, tool arguments, routing, judges, SQL/code generation, anything parsed downstream | bland or repetitive prose; can get stuck in loops on long open-ended generation |
| `temperature` 0.7-0.9 | user-facing prose, release-note narrative, naming, marketing copy, chat personality | more variation to review; more chances to drift from the facts |
| `temperature` 1.0+ | brainstorming, deliberately sampling many candidates, synthetic data diversity, "give me 20 options" | hallucination risk rises; quality floor drops; only sane when a human or a filter picks the winner afterwards |
| `top_p` < 1 (temperature left at default) | you want to cut the tail without touching the shape — a decent "safer creativity" lever | interacts with temperature if you also move that; hard to reason about both |
| `top_k` | rarely; legacy / local-inference tuning | fixed size ignores model confidence |

Alternatives to reaching for temperature at all: better prompting and examples usually buy more
variety-with-quality than a higher temperature; and **sample-N-then-pick** (generate 5 candidates at
0.8, score them, return the best) gives you diversity *and* a quality gate, at 5x cost.

## Production considerations

- **Always set it explicitly.** Provider defaults vary (OpenAI-compatible APIs commonly default to
  `temperature=1.0`; some SDKs default differently; some endpoints ignore the field entirely). A
  default is a decision someone else made for a different use case. Set it in the provider layer
  (`packages/llm-kit`) per call-site, and log it with every request alongside the model and usage.
- **Reasoning models restrict these knobs.** Several reasoning/thinking models reject
  `temperature`/`top_p` outright, silently ignore them, or only accept the default — because the
  sampling regime is part of how the reasoning was trained. Check per model; never assume the
  parameter took effect, and confirm by measuring variance rather than by reading docs.
- **Temperature affects eval stability, not just output.** A high-temperature eval has wide
  confidence intervals; a 3-point "improvement" between two prompt versions may be pure sampling
  noise. Run evals at the temperature the feature actually ships with, and repeat N times; report a
  distribution, not a point.
- **Cost.** Temperature does not change per-token price, but it changes behaviour that costs money:
  higher temperature means more retries on schema failure, longer and more rambling outputs (more
  output tokens, which are the expensive ones), and more repair loops. Low temperature on structured
  output is a cost optimisation as much as a quality one.
- **Latency.** Effectively unchanged by these parameters; length is what drives decode time.
- **Caching.** Exact-match response caching is only sane at low temperature — caching a
  temperature-1.2 brainstorm defeats its own purpose.
- **Observability.** Log `temperature`, `top_p`, `seed`, model string, prompt version, and
  `finish_reason` on every call. When output quality changes next month, these are the only columns
  that let you tell "we changed something" from "they changed something".
- **Reproducibility contract.** The strongest honest statement is: same prompt + same model version
  + `temperature=0` + `seed` → *usually* the same output. Design the system so that "usually" is
  acceptable, rather than assuming "always".

## Interview questions

1. *What does temperature actually do, mathematically and practically?*
   It divides the logits by T before the softmax. T<1 sharpens the distribution toward the argmax;
   T>1 flattens it and lifts the tail. It configures the sampler, not the model — the forward pass
   and the logits are unchanged. Applied once per token, so an early divergence compounds.
2. *What is the difference between temperature and top_p, and why shouldn't you tune both?*
   Two different steps in the same pipeline: temperature reshapes the probability distribution,
   top_p truncates it by cumulative mass (keeping the smallest set of tokens whose probabilities
   sum to p), so top_p adapts to the model's confidence. Tuning both makes the interaction
   non-linear — changing temperature moves where the top_p cut falls — so you can no longer
   attribute a behaviour change to either knob. Convention: tune temperature, leave top_p at 1.0.
3. *Why does temperature 0 not guarantee determinism? What do you do about it?*
   T=0 removes sampling randomness only. Floating-point non-associativity in batched GPU kernels
   means results depend on batch composition, which on shared infrastructure depends on other
   users' traffic; MoE routing can vary with batching; and providers update models behind a stable
   name. So tests never assert exact strings: assert schema validity, invariants, set membership,
   numeric bounds, or semantic similarity with a threshold, and report pass rate over N runs.
4. *How would you design an experiment to measure the effect of temperature?*
   Fix the model and prompt, vary temperature over at least three points (0.0 / 0.7 / 1.2), run N
   samples per point, and measure variance numerically — distinct output count plus mean pairwise
   similarity — rather than eyeballing. Crucially, run at least two prompt types (open-ended and
   factual), because output variance is a property of the underlying distribution, not of the
   temperature alone; a factual prompt alone would show almost no effect and support a false
   conclusion.
5. *Where would you use different temperatures inside one product?*
   Changelog Forge: the map stage classifies each commit into a category and emits structured JSON
   — temperature 0-0.2, because there is one right answer and the output is parsed. The reduce
   stage writes the human-facing release narrative — temperature ~0.7, because there are many good
   phrasings and the output is read by a person. Same product, same pipeline, two settings, and the
   reason is "is the output parsed or read?".
6. *A colleague raises temperature to reduce repetitive output. Better options?*
   Frequency/presence penalties target repetition directly; prompt and few-shot changes usually buy
   more variety per unit of risk; and sample-N-then-rank gives diversity with a quality gate.
   Raising temperature lifts the whole tail, including the factually wrong part of it.
7. *Your JSON extractor fails to parse about 3% of the time in production and never locally. First
   three things you check?*
   The temperature actually being sent (a default of 1.0 that nobody set); `finish_reason ==
   'length'`, i.e. truncation rather than a model-quality problem (exp-002); and whether the model
   string resolves to the same version in both environments. Then: validate-and-repair loop, and
   log the raw body on every parse failure.

## Project application

**Changelog Forge** (Phase 1) uses two settings in one pipeline, and this note is the justification
that goes in `docs/decisions/`:

- **Map stage** (cheap model classifies each commit group into `feature | fix | breaking |
  internal` and emits a structured `Change`): `temperature=0`, `top_p` untouched. Parsed output,
  one correct answer, and the eval scorers are code-based — any variance here is pure downside.
- **Reduce stage** (better model merges, dedupes, writes the end-user and developer narratives):
  `temperature≈0.7`. Read by a human, many acceptable phrasings, and blandness is a real product
  failure for release notes.
- **Eval harness**: run at the shipping temperature, N repetitions per golden item, report pass
  *rate*. Coverage and link-validity scorers assert properties (every expected breaking change
  mentioned, no hallucinated PR numbers, links resolve), never exact strings. Prose quality goes to
  an LLM judge at temperature 0 with a rubric — and the judge is repeated too.
- **`llm-kit`**: `temperature` is a required argument at each call site, not a default buried in the
  client, and it is logged with the model, prompt version and usage on every call.

## Limits of what exp-003 will prove

To record honestly once the run exists:
- **n=5** detects gross differences, not subtle ones. No confidence intervals; do not quote a
  similarity number to three decimals.
- **One model, one provider** (Groq `openai/gpt-oss-20b`, an MoE model). Findings about T=0
  variance may be MoE- or Groq-specific.
- **One similarity metric.** Whatever is used (token overlap, ratio-based, or embedding cosine)
  measures surface form, not meaning; two semantically identical outputs can score low.
- **Two prompts** is enough to show content-dependence exists, not enough to characterise it.
- **One day, one run of the whole lab.** Provider-side model updates are exactly the confound this
  concept warns about, and a single day cannot see them.

## References

- `EXPERIMENTS.md` exp-003 (to be added after the run) — own measurements.
- `labs/03-params/NOTES.md` — full run output (owned by another agent; link once it exists).
- `notes/concepts/tokens-and-context-windows.md` — exp-002; the "one sample is not data" lesson and
  the `finish_reason` check both carry forward here.
- Provider API references for parameter support per model (re-verify per model; reasoning models
  differ) — checked 2026-09-17.
