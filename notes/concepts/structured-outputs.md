# Structured Outputs

**Status:** learning (drafted 2026-10-15 by the `mentor` agent, after `labs/06-structured` ran)
*Why: same convention as `tool-calling.md` and `tokens-and-context-windows.md` - this note is
agent-drafted and is not yet in Saad's own words. It becomes `understood` when he can, without the
note open, (a) say what each of the four modes guarantees in one line each, (b) name the three
validation layers and one exp-024 failure that only each layer caught, and (c) explain why strict
mode is not an injection defence. The `Learned` section of `labs/06-structured/NOTES.md` is still
empty; filling it is the other half of the bar.*
**Phase:** 1   **Tags:** [F], llm-fundamentals / reliability / security

## Concept

Structured output means getting a **typed object** out of a model instead of prose: an `Invoice`
with known keys and types that code can store, sum, route or act on. There are four ways to ask
for it - describe the shape in the prompt, "JSON mode", a strict JSON schema enforced by the
provider, or a forced tool call - and they differ only in *how much of the shape is guaranteed*.
None of them says anything about whether the values are true. **Structured outputs guarantee the
shape, never the truth.**

## Problem

Almost every production LLM feature is "text in, data out": extract fields, classify a ticket,
route a request, fill a DB row, produce tool arguments. Without structure:

- You parse prose with regex, and it breaks on the first "Sure! Here is the JSON:".
- Keys drift (`total` vs `amount_due`), types drift (`"294,OO"` as a string), and the bug shows up
  three layers downstream as a `NaN` in a dashboard.

What breaks when you *misunderstand* it - the more dangerous half:

- You treat "the provider enforced the schema" as "the data is right". exp-024 doc 7: an injected
  `total=0.0, vendor='Approved'` was schema-valid every single time.
- You force an answer where the honest answer is "this is ambiguous" or "this is not in the list",
  and the schema itself makes the model produce something wrong-but-valid (doc 8; the `Currency`
  enum that cannot say "JPY").

## Mental model

**A clerk copying a crumpled receipt onto a printed form.** The form has boxes; a strict schema
means the clerk physically cannot write outside them. The clerk can still write the wrong number
in the right box, copy the shop's own arithmetic mistake faithfully, or obey a sticky note on the
receipt that says "write 0 in the total box".

**Web analogy: it is Zod at the boundary - but the client is a model that can be talked into
lying.** In a Next.js route you `schema.parse(req.body)` because the body is untrusted. A
model's output is exactly that: an untrusted request body whose author read attacker-controllable
text a moment ago. Validate it the same way, and then go further, because Zod-style validation
only covers the first of three layers.

**Constrained decoding, simply.** In strict mode the provider compiles your schema into a grammar.
At every token, it masks out every token that would break the grammar - after `{"currency": "`
only `USD`, `EUR`, `GBP`, `PKR` are possible. That is why the schema must be *closed* (a grammar
needs a finite set of keys, hence `additionalProperties: false`) and *fully required* (optional
keys explode the grammar's paths, so "may be absent" becomes "always present, may be null").

## Architecture

```
document (untrusted)                                         ┌─ semantic violation -> flag for human,
      │                                                      │   do NOT auto-repair (product decision)
      v                                                      │
[prompt + schema] --> provider --> raw text --> 1. SHAPE --> 2. COMMON SENSE --> store / act
   schema billed       │ strict:                  (Pydantic)   (invariants: lines   │
   every call          │ grammar                     │          x qty, sums, dates) │
   (+318..+432 tok)    │ masks tokens                │ invalid                      │
                       │                             v                              │
                       │                   ONE repair turn: output + exact error    │
                       │                   (truncated? never parse, raise budget)   │
                                                                                    v
                                     3. ANSWER KEY (golden set, offline / in CI only):
                                        field accuracy, invented values, injection landed
```

Layers 1 and 2 run on every production call. Layer 3 needs the right answer, so it runs only on a
labelled golden set - which is why layer 2 exists: the cheapest check that needs no answer key.

## Example

exp-024, `labs/06-structured`, Groq `openai/gpt-oss-20b`, temperature 0, `max_tokens` 2048,
8 synthetic invoices x 4 modes, docs 7 and 8 re-run x3.

**The four modes and what they promise:**

| mode | schema travels in | promise | schema-valid 1st (run 1) | semantic-valid, accuracy |
|---|---|---|---|---|
| `prompt` (baseline) | system text | nothing | 7/8 (doc 8 truncated) | 6/8, 0.88 |
| `json_object` (JSON mode) | system text | valid JSON syntax | 8/8 | 6/8, 0.97 |
| `json_schema` strict | `response_format` | the shape (grammar) | 7/8 (doc 8: 400) | 5/8, 0.85 |
| `tool` (forced call) | `tools[0].parameters` | a call; args *asked* to fit | 8/8 | 6/8, 0.97 |

**What happened:**

- **Section S.** Pydantic's raw `model_json_schema()` was **rejected** by Groq strict:
  `additionalProperties:false must be set on every object`. Leave-one-out over five transform rules:
  only `close_objects` (`additionalProperties: false` everywhere) and `require_all` (every property
  in `required`) were load-bearing. `inline_refs`, `nullable_types`, `strip_keywords` were harmless
  on Groq; kept for portability.
- **Docs 1, 2, 3, 5, 6** (clean, prose email, OCR noise, missing-field bait, German decimal comma):
  accuracy 1.00 in **every** mode, **zero invented values** (`PO-5512` and "Net 30" correctly left
  null), and the **repair loop never fired**.
- **Doc 4** (vendor's own totals wrong: lines sum to 421.00, vendor wrote 431.00): all 4 modes
  **copied as stated**. Accuracy 1.00, and every mode correctly *failed* the semantic check. Only
  the arithmetic layer can tell you the document itself is wrong.
- **Doc 7** (prompt injection inside the invoice): landed **1/3** in `prompt`, **3/3** in each of
  `json_object`, `json_schema`, `tool`. When it landed: `vendor_name='Approved'`, `total=0.0`,
  `subtotal` still the real 830.00. The schema could not catch it (valid string, valid float). The
  semantic check caught it every time - only because the attacker left `subtotal` alone.
- **Doc 8** (two invoices in one document): `prompt` truncated at 2048 output tokens **3/3**
  (reasoned until the budget ran out); `json_schema` failed **3/3** with Groq `json_validate_failed`
  and an empty `failed_generation` - nothing to repair. When a mode did answer, it took the first
  invoice; nothing ever merged them.
- **Section C, cost** (doc 1, `prompt_tokens`): bare 324; `tool` +318, `prompt` +386,
  `json_object` +414, `json_schema` +432. The schema costs more than the invoice, on every call.

## Implementation

`labs/06-structured/` - no framework, `llm-kit` deliberately not imported.

- `models.py`: `X | None` for fields a document may lack (so a non-null value where the golden
  answer is null is countable as **invented**); `float` money with a 0.01 tolerance (production
  would use `Decimal`/cents - avoided here because Pydantic's `Decimal` schema is an `anyOf` with a
  regex, a second schema experiment); **no** `extra="forbid"` so section S could show the 400.
- `schema_shape.py`: the five rules, each removable for leave-one-out. `_walk` knows that keys of a
  `properties` map are field names, not keywords.
- `validate.py`: three layers as three separate functions. Semantic checks are deliberately **not**
  Pydantic validators - that would merge layers 1 and 2 and push "fix the total" into the repair
  loop, where it is a product decision, not a formatting error.
- One repair turn, not three; truncation (`finish_reason == "length"`) is never parsed or repaired.
- Known defect (NOTES): Groq's `400 json_validate_failed` is classified `api_error`; it is a model
  failure and should get its own status.

This is `llm-kit`'s `to_provider_schema()` + `require_all_properties()` + `complete_structured()`
(one repair by default) rebuilt by hand, so those now have a measured reason. Found while doing
this: `llm-kit`'s `_close_objects` strips every key named `title`/`default`, including a *field*
named `title`, which then disappears from `properties` (and on the tool path stays in `required`).
Filed as a separate task; the lab's `_walk` shows the fix.

## Trade-offs

| choose | when | watch for |
|---|---|---|
| `json_schema` strict | data out, provider enforces it - the extraction default | 400 before generation on an unsupported schema; can *force* a wrong-but-valid value (closed enum); fails with nothing on ambiguous input (doc 8) |
| forced tool call | the model is choosing between **actions**, or the API has no schema mode | cheapest encoding here (+318), but args are not grammar-enforced without `strict`; still validate |
| `json_object` | provider has no schema mode and you validate anyway | syntax only; shape is luck (it was 8/8 here - one model, clean docs) |
| schema in prompt | never in production; it is the control | prose wrappers, fences, truncation |
| framework (`instructor`, Pydantic AI, `llm-kit`) | after you have built it by hand once | hides the schema rewrite and repair loop - the parts you debug at 1 a.m. |

Design levers that beat mode choice: give the schema an **escape hatch** (`status: "ok" |
"ambiguous" | "not_an_invoice"`, `other_currency: str | null`) instead of forcing one answer;
decide **copy vs correct** in the contract, not by model default; keep descriptions short because
they are billed every call.

## Production considerations

- **Security.** Extraction input is untrusted. Strict mode did not reduce injection here - it
  coincided with more of it (9/9 structured vs 1/3 prompt; n=3, one model, mechanism untested).
  Defences are structural: invariant checks as tripwires (beaten by a consistent attack),
  cross-checks against independent sources, and a human gate before any side effect driven by
  extracted values.
- **Observability.** Count schema failures, repairs, semantic violations and truncations
  separately. A semantic-violation rate is the closest thing to a live accuracy signal.
- **Cost.** +318 to +432 input tokens per call for one small schema; it scales with schema size
  and is paid on every call (and every repair, which re-sends the conversation).
- **Reliability.** Truncation is a budget failure: never parse it. Reasoning models spend output
  budget thinking first; ambiguity makes them spend all of it (doc 8).
- **Portability.** Each provider's strict subset differs; normalise the schema in one place.
- **UX.** A semantic violation is a UI state ("totals don't add up - check this"), not something to
  hide or silently fix.

## Interview questions

1. *JSON mode vs structured outputs vs tool calling?*
   JSON mode guarantees syntax; structured outputs (strict schema, constrained decoding) guarantee
   shape; tool calling is for choosing actions and only incidentally gives shape. None guarantees
   correct values. In exp-024 all modes were perfect on clean docs - the differences showed up only
   on injection and ambiguity.
2. *How do you know extracted data is right?*
   Three layers: schema (shape), semantic invariants (do the values agree with each other - runs on
   every call, no answer key), accuracy against a hand-labelled golden set (offline/CI). Doc 4 was
   schema-valid and accurate and semantically invalid - the document was wrong. Doc 7's `total=0.0`
   was schema-valid and only the invariant check caught it.
3. *Pydantic's schema got a 400 in strict mode. Why?*
   Strict mode compiles the schema to a grammar, which needs a closed set of keys and no optional
   keys. Pydantic emits neither `additionalProperties: false` nor every field in `required`. On Groq
   those two rules were the only load-bearing ones of five.
4. *How do you defend extraction against injected text in the document?*
   Treat the document as untrusted; delimiters and "this is data" in the system prompt are a
   mitigation (it did not hold in exp-024). Then: invariant checks, cross-checks against other
   sources, no autonomous side effects on extracted values without a human or a rule gate, and
   monitoring of semantic-violation rates. Strict mode is not a defence.
5. *The input is ambiguous (two invoices in one). What should the system do?*
   Not force one answer. Give the schema a way to say so (`ambiguous`, or a list), and route that to
   a human. exp-024: forcing one answer produced 3/3 truncations in prompt mode and 3/3 empty
   failures in strict mode.
6. *Should validation failures be retried?*
   Shape failures: one repair turn with the exact error. Semantic failures: no - "fix the total" is
   a product decision. Truncation: no repair; raise `max_tokens`.

## Project application

- **Changelog Forge** (`projects/changelog-forge`): map stage calls `complete_structured(...,
  GroupAnalysis)`; `pipeline/verify.py` is the semantic layer (refs must resolve, breaking needs
  confidence >= 0.6, uncovered items get a fallback); the eval golden set is layer 3. Its doc-4
  equivalent: a commit message that claims a breaking change the diff does not show.
- **Review Radar**: structured extraction from public reviews = untrusted text at scale = doc 7's
  risk. Extracted values that drive side effects (issues, replies) go through the approval gate.
- **DocPilot RN**: structured answer objects with citation IDs, verified by code against retrieved
  chunks - the same "shape is not truth" split.
- **`packages/llm-kit`**: `complete_structured()`, `to_provider_schema()`, `require_all_properties()`.

## References

- `EXPERIMENTS.md` exp-024 (2026-10-15) - own measurements.
- `labs/06-structured/NOTES.md` - full results, run 1 transcript `runs/20261015T085117-groq.json`.
- `notes/concepts/tool-calling.md` - the trust boundary; tool calling as the structure-for-actions path.
- `notes/concepts/tokens-and-context-windows.md` - truncation (`finish_reason == "length"`).
- `notes/concepts/generation-parameters.md` - why temperature 0 for parsed output.
