# llm-kit

A thin, fully-understood provider layer over any OpenAI-compatible LLM API.

**Not a framework.** ~800 lines including comments, and the acceptance criterion is that
every line can be explained on demand. LangChain does all of this and much more; the point
of writing it by hand is that when a framework misbehaves you will know what it was trying
to do (CLAUDE.md rule 6).

```python
from llm_kit import LLM, Ledger

ledger = Ledger(max_usd=0.05)          # a hard ceiling, checked BEFORE each call
llm = LLM(provider="groq", tier="fast", ledger=ledger)

print(llm.complete("Say hello in five words.").text)
print(ledger.summary())
# 1 calls  23 in / 9 out (0 hidden reasoning)  $0.000004 at paid rates
```

## The four methods

| Method | In / out | Notes |
|---|---|---|
| `complete()` | text -> text | `.truncated` tells you when `finish_reason == "length"` |
| `complete_structured()` | text -> a validated Pydantic instance | native schema enforcement, Pydantic validation, then one capped repair attempt |
| `stream()` | text -> an iterator of chunks | records usage via `stream_options` so streamed calls are not free in the ledger |
| `call_tools()` | text -> an agent loop -> answer | iteration cap **and** wall-clock deadline, plus the ledger budget |

Everything routes through one private `_execute`, which is the only place that checks a
budget, paces, times, retries, and records. That single chokepoint is why the cost numbers
can be trusted: there is nowhere else a call can originate.

## What it deliberately does not do

Prompt templating (projects own their prompts, versioned as files), chains, memory, RAG,
or anything that would make replacing this library expensive. The line: **llm-kit knows
about providers, projects know about problems.**

## Design decisions worth knowing

**Four error types, not one.** `LLMTransientError` (429/5xx/timeouts) retries with
exponential backoff and full jitter, honouring `Retry-After`. `LLMPermanentError`
(400/401/403/404/422) raises immediately — retrying a bad API key five times turns one
clear error into a slow, confusing one. `LLMBudgetError` is our own guard firing.
`LLMOutputError` means the call succeeded and the *content* is unusable.

**Jitter is not a nicety.** Without it, N callers rate-limited at the same instant all
sleep exactly 1s and wake together — a thundering herd that reproduces the 429 that caused
it.

**Cost is computed at paid rates even on the free tier.** "Free tier" is a quota, not an
economics lesson. The number that decides whether a feature can ship is cost per user
action at paid rates, and measuring it from day one costs nothing. An unpriced model is
charged at the worst known rate and flagged, because a missing price silently reading
`$0.00` is a reassuring lie in a cost report.

**Structured output is three layers.** Ask the provider to constrain generation; validate
with Pydantic anyway (native modes still fail on semantics, and some providers treat
`strict` as advisory); then, once, hand the model its own broken output plus the
validator's complaint. Capped at one repair by default — a model that got the shape wrong
twice usually gets it wrong a third time, and each attempt is a full-price call.

**`schema.py` exists because of a real 400.** The first live `smoke.py` run failed with
``` `additionalProperties:false` must be set on every object ```. Pydantic's
`model_json_schema()` is correct JSON Schema and is rejected by every strict
structured-output implementation we use, because a grammar cannot be compiled from a
schema that leaves the legal key set open. Normalisation (inline `$ref`s for Gemini, close
every object for OpenAI/Groq, strip `title`/`default` noise) lives in one shared module so
a tool schema and a response schema can never disagree about what a provider accepts. This
is the portability leak `TECHNOLOGY_STACK.md` predicted, found the only way it can be
found: by calling a real provider.

**The tool loop has two guards, not one.** `max_iterations` caps steps; `deadline_s` caps
wall-clock time. A tool that hangs 90 seconds six times passes an iteration cap
comfortably while taking nine minutes. (This closes the open question `labs/04-tools`
ended on.)

## Tests

```bash
uv run pytest -q     # 42 tests, no network, ~1s
uv run ruff check . && uv run ruff format --check .
```

No test calls a real model. A suite that hits a live LLM is slow, costs money, burns quota
and is non-deterministic — so a red build tells you nothing. The plumbing (retries,
budgets, validation, message ordering) is fully deterministic and belongs in pytest.
Judging whether the model's *answer* is good is a different activity with a different name
— evals — and it lives in each project's `evals/`.

```bash
uv run smoke.py                    # ~7 live calls against Groq, prints a cost ledger
uv run smoke.py --provider gemini
```

`smoke.py` is the other half: it proves the fakes resemble reality. It is what caught the
schema bug above.

## Providers

`gemini` (primary), `groq` (secondary, fast — good for agent loops), `openrouter` (model
zoo, experiments only), `ollama` (local). Each carries its own `quirks` list of documented
places where "OpenAI-compatible" stops being true. Read them; that list is the actual
portability knowledge.

Keys come from the workspace `.env` via `pydantic-settings`, held as `SecretStr` so an
accidental `print(settings)` emits `**********` rather than an API key.
