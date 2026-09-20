# Lab 04 notes: tool calling

**Question.** What is actually happening when a model "uses a tool"? Lab 03 measured what
the sampling knobs do to a single completion; this is the first lab with a **loop**, and
the loop is the entire mechanism behind the word "agent". Two things get measured rather
than asserted: (1) what the message array looks like at every step, printed in full, and
(2) what that array **costs**, which closes the open question lab 02 left behind —
*"does the wrapper grow with a system message and with tool schemas?"*

No framework. No LangChain, no Pydantic AI, no SDK tool runner. `openai`, `json`, and a
hand-written `while`, per CLAUDE.md rule 6: build the concept once before adopting the
thing that hides it.

**Prediction, written before the run** (per the week plan, R5 — if this turns out wrong,
leave it wrong and say so, a prediction edited after the fact teaches nothing):

- The two tool schemas together will cost **more than lab 02's whole +71 wrapper** — my
  guess is +200 to +350 `prompt_tokens`, paid again on every single step.
- `prompt_tokens` will roughly **double** between step 1 and the final step of section B.
- The model will batch both `get_weather` calls into **one** assistant turn with two
  `tool_calls` (parallel calling), not take a turn per city.
- Given a `ToolError` that lists the valid cities, the model will **recover** — either by
  calling a listed city or by reporting the limitation — rather than inventing a reading.
- The hidden-reasoning share will be **lower** than lab 03's 84–95%, because emitting a
  tool call is closer to structured output than to open-ended prose.

**Setup.** `uv run main.py` (run `--dry-run` first for the call plan). Provider is **Groq**
`openai/gpt-oss-20b`: it supports tools and answers in ~1 s (lab 02 §C), and a loop makes
several *sequential* calls per prompt, so latency compounds in a way it did not in labs 02
or 03. `--provider gemini` exists for a cross-provider spot check. Temperature is **0**
because tool arguments are parsed, not read — the exp-003 rule applied to a case where
"a different but equally good phrasing" is a crash, not a style choice. `MAX_TOKENS=2048`,
double lab 03's, because lab 03's first run was voided at 256 by hidden reasoning and a
tool call gives the model strictly more to think about.

Two tools, both synthetic and offline (free-tier prompts train the provider's models —
TECHNOLOGY_STACK.md §1), chosen so each isolates a different half of the lesson:

| Measurement | What it is | What it isolates |
|---|---|---|
| `get_weather(city)` | deterministic dict lookup, clearly labelled fake, no key and no network | the **happy path** and, for any city outside the fixture, a real `ToolError` — a tool that can fail is what makes the loop interesting |
| `calculate(expression)` | `ast.parse(mode="eval")` + an allowlist walk over numbers and `+ - * / **` | the **trust boundary**. Model output is attacker-influenced text; this is where it stops being treated as trusted. No `eval`, ever |
| §A happy | one prompt, one tool | the minimum complete cycle: model → `tool_calls` → execute → append → model → answer. The message array is printed in full at every step |
| §B both | a prompt needing weather *and* arithmetic | whether the model **batches** two calls into one assistant turn (parallel calling) — the reason the loop iterates a `tool_calls` **list**, not `tool_calls[0]` |
| §C raises | `get_weather("Reykjavik")` | the failure that is *normal operation*: the error becomes the tool result, the model reads it and adapts. The error string lists the valid cities on purpose — a tool error is a prompt |
| §D unknown | a hand-injected call to `get_stock_price` | that an unadvertised name is refused on the **name alone**, before argument parsing. `TOOL_FUNCTIONS` is an authorisation list, not a lookup convenience |
| §E badjson | a hand-injected `arguments` string cut off mid-value | `json.loads` failing on model output, and the `JSONDecodeError` (with its position) going back as the tool result so the model can reissue |
| §F guard | same loop, `max_iterations=2`, a prompt needing six lookups | the circuit breaker firing, reported as a **failure** rather than returning mid-loop chatter as if it were an answer |
| §G schemas | the same user message sent 5 ways: bare / +system / +weather / +calculate / +both | the **per-schema token cost**, measured. `max_tokens=1` because only `usage.prompt_tokens` is read |
| `prompt_tokens` per step + delta | printed on every step of every loop | that the conversation **is** the state: the whole array is re-sent and re-billed every step. Cumulative billed input is the agent cost model in one number |
| `finish_reason` | checked on every step | carried forward from labs 02/03, but here it is a **safety** check, not a data-quality one — see below |

**Why §D and §E are injected.** A model requests a non-existent tool, or emits broken
JSON, rarely — rarely enough that waiting for it is not an experiment. Those two assistant
turns are hand-written by `synthetic_assistant()`, marked `[synthetic]` in the output, and
cost no API call. The **failure is staged; the recovery is not** — the loop continues for
real from there, so what gets measured is the thing that matters: what the model does
after it reads the error. Code that has never executed its error path does not have one.

**`finish_reason="length"` is a different animal inside a tool loop.** In prose it gives a
sentence that stops mid-w. On a tool call it gives a **truncated `arguments` JSON string**,
and that ends one of two ways: `json.loads` raises (the lucky case), or the cut happens to
land somewhere that still parses — `'{"city":"Kara"}'` — and you execute a call the model
never finished writing. With a real tool (a payment, a `DELETE`, an email) that is a
truncated string turning into a wrong, irreversible action. So `run_loop()` discards a
`length` turn with pending tool calls **unexecuted** and stops. Raise `MAX_TOKENS`; never
repair the JSON.

**No cache, on purpose** — same contract as lab 03, and if anything stronger. A cached step
hands back a stored tool call and measures nothing about how the model behaves when it
reads a real error. The loop *is* the experiment. What is written to disk is a transcript
under `runs/<UTC timestamp>-<provider>.json` carrying the timestamp, the provider, the
exact model id, the tool schemas as sent, and the **full message array after every step** —
a tool loop is not reconstructable from a summary. Provenance, never replayed.

Pacing: `rate_limit()` unchanged from lab 03 — sleeps **before** each call, for only the
time still owed since the previous call started, on the error path too, never after the
last call. It matters more here: lab 03's call count was fixed by its plan, a loop's is
decided by the model at runtime, so pacing has to live at the call site.

`max_retries=0` on the client, also unchanged, and also for a new reason: an automatic
retry would re-send an identical message array and could produce a **second set of tool
calls for work that already ran**. For a real tool that is a duplicate side effect.

---

## Results (run 1, 2026-09-20)

Command: `uv run main.py` · Model: `openai/gpt-oss-20b` (Groq)
Transcript: `runs/20260920T071652-groq.json`
13 model calls, $0.000831 at paid rates ($0 on the free tier).

> **Run 0 crashed after the loop had already succeeded.** `UnicodeEncodeError` on U+202F
> (narrow no-break space) in a weather sentence: Windows stdout defaults to cp1252 and
> model output is arbitrary Unicode. The failure was in `print()`, not in the tool loop.
> Fixed by reconfiguring stdout to UTF-8 with `errors="replace"`.

### A. The loop, fully visible

```
step 1 [model]  fr=tool_calls  in=440   out=?    -> get_weather({"city":"Karachi"})
step 2 [model]  fr=stop        in=485   +65      -> final answer
cumulative billed in = 905
```

Four messages by the end: `system`, `user`, `assistant(tool_calls)`, `tool(result)`.
The +65 between steps is the tool call plus its result being re-sent.

### B. Both tools — and the model did NOT batch

| step | fr | in tok | delta | tool requested |
|---|---|---|---|---|
| 1 | tool_calls | 436 | (first) | `get_weather({"city":"Lahore"})` |
| 2 | tool_calls | 500 | +64 | `get_weather({"city":"London"})` |
| 3 | tool_calls | — | — | `calculate(...)` |
| 4 | stop | — | — | final answer |

**One `tool_calls` entry per turn, never a batch**, on a prompt that plainly allowed two
weather lookups at once. 4 model calls, 2094 input tokens billed for one question.

### C. A tool raises

Reykjavik is not in the fixture. `[ERR]` -> the error JSON (which lists the valid cities)
goes back as the tool result -> step 2 `fr=stop`, model explains the failure. 2 steps,
recovered without a crash.

### D. A tool that does not exist

Synthetic assistant turn calling `get_stock_price`. Refused **on the name alone, before
argument parsing** — `TOOL_FUNCTIONS` acts as an authorisation list. The model then
answered the arithmetic half of the question. 2 steps.

### E. Malformed JSON in `arguments`

Synthetic truncated blob `{"expression": "(1280 * 3) / `. `json.loads` raises; the
`JSONDecodeError` message *and position* go back as the tool result; the model reissues
the call correctly. 3 steps.

### F. The max-iteration guard

Six cities requested, `GUARD_ITERATIONS = 2`. Because the model fetches one city per turn
(section B), it could not finish, and the guard fired — reported loudly as a FAILURE with
`final_text=None` rather than returning a half-answer.

### G. What the envelope costs — closing lab 02's open question

| variant | prompt_tokens | vs bare |
|---|---|---|
| bare (user message only) | 80 | +0 |
| +system | 152 | +72 |
| +weather schema | 235 | +155 |
| +calculate schema | 220 | +140 |
| +both schemas | 348 | +268 |

`both` (+268) < `weather` + `calculate` measured separately (+295), so the cost decomposes:

| component | tokens | paid |
|---|---|---|
| one-off framing block (any tool present) | **27** | once per request |
| `get_weather` schema | **128** | per request |
| `calculate` schema | **113** | per request |
| system prompt | **72** | per request |

**Lab 02's open question is answered: yes, the envelope grows, and by a lot.** Lab 02
measured Groq's bare wrapper at a constant +71. Adding a system message and two modest
tool schemas takes the envelope to **+268 tokens before the user has said anything** —
and it is re-sent on every step of the loop.

### Summary

```
section           steps  in tok  out tok    cost $  stopped because
A-happy               2     905       93  0.000096  final answer
B-both                4    2094      174  0.000209  final answer
C-raises              2     948      108  0.000103  final answer
D-unknown-tool        2     493      130  0.000076  final answer
E-malformed-json      3    1046      265  0.000158  final answer
F-max-iterations      2     993      381  0.000189  max iterations
TOTAL             13 model calls, $0.000831
```

---

## Learned

<!-- Saad's own words. Do not paraphrase the script's output back — the script already
     printed the numbers; this section is what they MEAN. One or two sentences each:

     - The provider stored nothing between steps: every call re-sent the whole array.
       So what is "an agent's memory", literally? Use your own numbers from §A/§B — what
       did prompt_tokens do from step 1 to the last step, and what does that imply for a
       20-step agent, or for one with ten tools instead of two?

     - §G gave you a real number for what one tool schema costs, paid on EVERY step.
       Multiply it out for a loop of N steps with T tools. Then answer the design
       question: when is "just add another tool to the list" the wrong move, and what
       would you do instead? (Name the alternative — routing, sub-agents, fewer tools
       with richer arguments — and say why you picked it.)

     - `calculate` uses an AST allowlist instead of `eval`. Explain the threat model in
       your own words WITHOUT using the phrase "the model might". Where does the text in
       `arguments` actually come from in a real product, and which of those sources can
       an attacker write? Then: name one tool you would want in Changelog Forge and say
       what its equivalent of "no eval" is.

     - Required, two sentences, concrete and from YOUR work (frontend/mobile, not a
       textbook): one place you would give a model a tool and one place you would NOT,
       and what decides it. Name the actual feature.

     - `finish_reason="length"` with tool_calls attached: why is that worse than the same
       finish_reason on prose? You have lab 02 §D (truncated JSON) and lab 03's voided
       run 0 as precedent — what is the rule you would write into `llm-kit` because of it?

     - A tool raised and the loop kept going (§C). Who wrote the words the model read
       about that failure, and what changed because that string listed the valid cities?
       What does that make a tool's error message, in prompt terms? -->

## Open questions for later labs

<!-- Carry at least one forward. Candidates:

     - §G split the schema cost into a fixed framing block plus a per-tool cost. Is that
       split the same on Gemini, or is it Harmony-format-specific like lab 02's +71 may
       be? One `--provider gemini` run of `--only schemas` settles it, and it is still
       the #1 open question carried from lab 02 and lab 03.

     - Does tool-call accuracy change with temperature at all, or is the schema
       constraining the grammar so hard that temperature has nothing left to sample?
       (This is lab 03 open question #5, now answerable: same prompt, temps 0 / 0.7 / 1.2,
       count how many produce a well-formed call to the RIGHT tool. Becomes exp-005.)

     - exp-012 on the backlog is "tool description quality vs agent success rate". The two
       descriptions in `tools.py` are a baseline. What happens with a deliberately vague
       one ("does maths") — does the model stop calling it, or call it wrongly?

     - Did the model ever do arithmetic itself instead of calling `calculate`? If so, is
       that fixed by the description, by `tool_choice="required"`, or not at all?

     - What does a tool result do to the hidden-reasoning share vs lab 03's 84-95%?

     - Parallel tool calls arrived in one assistant turn here. What breaks if you execute
       them concurrently instead of in order — and which of these two tools would be
       unsafe to run concurrently in a real system?

     - This loop has no timeout on total wall-clock time, only on step count. A tool that
       hangs for 90 s six times over is a different failure from six fast steps. Does
       `llm-kit` need a deadline as well as an iteration cap? -->
