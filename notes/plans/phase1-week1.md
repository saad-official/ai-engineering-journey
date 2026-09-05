# Phase 1, Week 1 (roadmap week 2) — Tokens and generation parameters

**Dates:** Mon 2026-09-07 → Sun 2026-09-13
**Phase:** 1 (Python for AI + LLM API fundamentals, roadmap weeks 2-5)
**Budget:** 8-12 focused hours. This plan commits ~9.9 h of core work, ~10.6 h with the stretch item.
**Planned by:** `pm` agent, 2026-09-05.

> Tracker note: resolved in `LEARNING_PLAN.md` by the main session on 2026-09-05. Phase 0 ran the
> week of Mon 2026-08-31 (week 1); this is the calendar week of Mon 2026-09-07 (week 2). The old
> `2026-09-08` in both rows was a Tuesday and is corrected.

---

## 1. The week in one sentence

**Goal.** By Sunday, Saad can count tokens for any text before sending it, explain exactly why two
providers report different token counts for the same prompt, and show measured evidence of what
temperature does to output variance.

**Explicitly not this week** (these are scope creep — defer, do not start):

| Deferred item | Where it actually belongs |
|---|---|
| `packages/llm-kit` — any of it, even "just the client wrapper" | Phase 1 week 3-4, after `structured` and `tools` labs exist to define its surface |
| Changelog Forge — spec, repo, collector, anything | Phase 1 week 4-5 (roadmap M1) |
| FastAPI, streaming, SSE | labs 05-06, Phase 1 week 3-4 |
| Structured outputs / Pydantic extraction | lab 04, Phase 1 week 2 |
| Refactoring `labs/01-hello-llm` into a reusable package | Never. Labs are allowed to be messy (`labs/README.md`) |
| A UI / visualiser for token boundaries | Not a portfolio artifact. A printed table is enough |
| The full 5.7 GB local model set | Phase 2. See §6 |
| Deploy / demo GIF | Nothing deployable exists this week. First deploy is Changelog Forge M5 |

**Cut line.** If by Saturday morning lab 02 is not finished, drop `labs/03-params` (tasks W2-T08 and
W2-T09) to week 3 and keep the reflect block. Core-minus-lab-03 is ~7.6 h. Never cut the reflect block —
an undocumented lab is a lab that did not happen.

---

## 2. Time allocation vs the weekly rhythm

| Block | Rhythm target | This week | Tasks |
|---|---|---|---|
| Theory | 2-3 h | 2.5 h | W2-T01, W2-T02 |
| Build | 5-7 h | 5.5 h (4.25 h if lab 03 is cut) | W2-T03 … W2-T09 |
| Reflect | 1 h | 1.9 h (deliberately over: two experiment rows + the first concept note) | W2-T10 … W2-T12, W2-T14 |
| Stretch | — | 0 h | W2-T13 (Ollama) - already done, see §6 |

Suggested shape for a full-time-job week — weekday evenings are theory and small increments, the
weekend carries the build:

| Day | Hours | Tasks |
|---|---|---|
| Mon 09-07 | 1.25 | W2-T01 |
| Tue 09-08 | 1.25 | W2-T02 |
| Wed 09-09 | 1.5 | W2-T03, W2-T04 |
| Thu 09-10 | 1.5 | W2-T05, W2-T06 |
| Fri 09-11 | 0 | Rest day. Protect it; consistency beats intensity |
| Sat 09-12 | 3.25 | W2-T07, W2-T08, W2-T09 |
| Sun 09-13 | 2.0 (+0.75) | W2-T10, W2-T11, W2-T12, W2-T14 (+W2-T13) |

---

## 3. Theory block (2.5 h)

Course: **"Large Language Models (LLMs) Concepts"**, DataCamp Bundle A, at `G:\courses\AI-Engineeering`.
`LEARNING_PLAN.md` assigns the whole course to Phase 1 week 1; it is the theory backbone for labs 02-04.
Video only — skip the in-browser coding exercises, they are 2023-vintage and OpenAI-account-specific.

| Chapter (approx. title) | Watch / skip | Why |
|---|---|---|
| 1 — Introduction to Large Language Models | Watch in full | Vocabulary: pre-training, inference, prompt, completion. Fast |
| 2 — Building blocks (tokenization, embeddings, attention, transformer) | **Watch twice if needed.** This is the chapter that pays for the week | Tokenization is lab 02. Embeddings here are just context — the real embeddings work is Phase 2 |
| 3 — Fine-tuning / N-shot / RLHF | Watch at 1.5x, take notes only on N-shot vs fine-tuning | Fine-tuning is out of scope for this roadmap, but "why we do not fine-tune" is an interview answer |
| 4 — Evaluation and ethics | Watch the evaluation half; skim the ethics half | Evaluation mindset seeds Phase 1 week 4 (`prompt-lab`). Ethics gets a proper pass in Phase 4 |

If the shipped chapter titles differ, follow the topics, not the numbers.

**Not this week, though `LEARNING_PLAN.md` allows it:** "Software Engineering Principles in Python"
(mapped to Phase 1 weeks 1-2) is deferred to week 3, where it lands next to `llm-kit` packaging and has
something to apply itself to. Frontend Masters lessons 5-6 (Zod schemas → tools) are deferred to the
`structured` / `tools` labs. Adding either to this week would push theory past 3 h and squeeze the build.

**Note-taking rule:** take notes straight into a scratch draft of
`notes/concepts/tokens-and-context-windows.md`. Do not write the note yet — W2-T11 writes it after the
labs supply the numbers. A concept note written before the measurement is a summary of a video, not knowledge.

---

## 4. Task list

Ownership column: **AI** = AI writes, Saad reviews and must be able to explain. **Hand** = Saad writes by
hand, no generated code, because the muscle memory or the reasoning is the point.

| ID | Task (verb-first) | Outcome: what exists when done | Est. | Deps | Owner | Definition of done (checkable) |
|---|---|---|---|---|---|---|
| W2-T01 | Watch LLM Concepts ch. 1-2 | Scratch notes on tokenization + transformer basics in a draft concept note | 1.25 h | — | Hand | Draft file exists with a written answer to: "why does a model see tokens and not characters or words?" |
| W2-T02 | Watch LLM Concepts ch. 3-4 (selective) | Scratch notes on N-shot vs fine-tuning and on evaluation | 1.25 h | T01 | Hand | Three bullets written on when fine-tuning would beat prompting, and why we are not doing it |
| W2-T03 | Scaffold `labs/02-tokens` | A `uv` project that runs: `pyproject.toml`, `.python-version` (3.12), `main.py` stub, `NOTES.md` stub | 0.5 h | — | **Hand** | `uv run main.py` prints something from a clean checkout; `ruff check .` passes; deps are `tiktoken`, `openai`, `pydantic-settings`, `httpx` only |
| W2-T04 | Count tokens locally for 5 texts | `main.py` prints a table: text label, chars, words, tiktoken count (o200k), chars-per-token ratio | 1.0 h | T03 | AI | Five texts of deliberately different shapes are used: English prose, code, JSON, a URL-heavy string, non-English text. Table printed, ratios differ visibly across the five |
| W2-T05 | Compare local counts against provider-reported usage | Same table gains columns: Gemini `countTokens`, Gemini `usage.prompt_tokens`, Groq `usage.prompt_tokens`, and the delta vs local | 1.0 h | T04 | AI | For each of the five texts, all four numbers are printed. The gap between a bare-string count and `usage.prompt_tokens` is measured, not guessed |
| W2-T06 | Re-measure Gemini latency over 10 sequential calls | A printed min / median / max / p90 for 10 identical calls, answering lab 01's open question | 0.5 h | T05 | **Hand** | 10 calls, sequential, ≥2 s apart, 60 s timeout each; result states whether 32.5 s was a cold first call or the steady state |
| W2-T07 | Write `labs/02-tokens/NOTES.md` | Lab 02 notes in the lab 01 format: question, setup, results table, learned, open questions | 0.5 h | T06 | **Hand** | Contains a one-sentence explanation of the 18-vs-88 token gap from exp-001, and at least one open question for a later lab |
| W2-T08 | Build and run the temperature study in `labs/03-params` | `labs/03-params` runs one prompt at temp 0.0 / 0.7 / 1.2, 5 runs each, and prints outputs plus a variance measure | 1.25 h | T03 | AI (runner) / Hand (analysis) | 15 completions captured to a file; a simple variance signal is reported (e.g. count of distinct outputs, or mean pairwise token overlap). Runs against **Groq**, not Gemini (see §7) |
| W2-T09 | Write `labs/03-params/NOTES.md` | Lab 03 notes plus the roadmap-mandated two sentences on when to use each temperature | 0.5 h | T08 | **Hand** | Two sentences exist naming a concrete use case for temp 0 and for temp ≥0.7 from Saad's own work, plus a recorded observation of whether temp 0 was actually deterministic |
| W2-T10 | Log exp-002 and exp-003 in `EXPERIMENTS.md` | Two new rows with real numbers; exp-001's Conclusion cell amended with the latency answer | 0.5 h | T07, T09 | **Hand** | Both rows follow the existing format (date, id, question, setup, result **with numbers**, conclusion, link). exp-001's open question about Gemini latency is now answered in-place |
| W2-T11 | Write `notes/concepts/tokens-and-context-windows.md` | The first durable concept note, using the `AI_CONCEPTS.md` template | 1.0 h | T07, T02 | **Hand** (AI reviews) | All template sections filled; **Status: understood**; Example and Implementation sections cite real numbers from lab 02, not generic examples; the box in `AI_CONCEPTS.md` is ticked |
| W2-T12 | Run the `reviewer` agent over the week's code | A short list of findings; the highest-value one is fixed | 0.5 h | T09 | AI | Findings recorded at the bottom of the relevant `NOTES.md`; at least one fix committed to the lab code, or an explicit "accepted, because…" for each finding not fixed |
| W2-T13 | ~~Install Ollama on G: with two small models~~ **ALREADY DONE** | Verified 2026-09-05: `G:\Ollama\ollama.exe`, `OLLAMA_MODELS=G:\ollama-models`, API serving `qwen3:1.7b`, `nomic-embed-text`, `qwen3-embedding:0.6b` (~2.2 GB) | 0 h | — | done | Met before the week started; lab 01 NOTES already records a local `qwen3:1.7b` run at ~13 tok/s. Phase 0 has no open items |
| W2-T14 | Fill the week 2 tracker row | `LEARNING_PLAN.md` week 2 row has Done and Blockers filled | 0.1 h | T12 | Hand | Done column lists what actually shipped, not what was planned. Blockers column is honest, including "ran out of evenings" |

**Total:** 9.85 h core, 10.6 h with W2-T13.

---

## 5. Reflect artifacts (the non-code deliverables)

| Artifact | File | Filled by | Content required |
|---|---|---|---|
| Experiment row | `EXPERIMENTS.md` → `exp-002` | W2-T10 | "Tokenizer vs provider usage counts." Setup = 5 texts, tiktoken o200k vs Gemini `countTokens` vs both providers' `usage`. Result must carry the actual numbers and the size of the fixed overhead per request |
| Experiment row | `EXPERIMENTS.md` → `exp-003` | W2-T10 | "Temperature variance study." Setup = 1 prompt × 3 temperatures × 5 runs on Groq. Result = distinct-output counts per temperature and whether temp 0 repeated exactly |
| Experiment amendment | `EXPERIMENTS.md` → `exp-001` Conclusion cell | W2-T10 | Append one sentence answering "was 32.5 s a cold call?" with the min/median/max from W2-T06 |
| Lab notes | `labs/02-tokens/NOTES.md` | W2-T07 | Lab 01's format |
| Lab notes | `labs/03-params/NOTES.md` | W2-T09 | Lab 01's format |
| Concept note | `notes/concepts/tokens-and-context-windows.md` | W2-T11 | Full `AI_CONCEPTS.md` template, status `understood` |
| Index tick | `AI_CONCEPTS.md` Phase 1 list | W2-T11 | `[x] tokens-and-context-windows` |
| Tracker | `LEARNING_PLAN.md` week 2 row | W2-T14 | Done + Blockers |

**One concept note only.** `generation-parameters.md` is the obvious second, and lab 03 produces exactly
its raw material — but two full template notes do not fit a 1 h reflect block, and a rushed note is worse
than none. Lab 03's `NOTES.md` is the seed; the note gets written in week 3 alongside lab 04, when
`top_p`, `stop`, and `max_tokens` have also been exercised and there is a full picture to write up.

**No deploy, no demo GIF this week.** Neither has a subject yet. Flagged so it is a decision, not an
oversight. The screenshot habit starts at Changelog Forge M1.

---

## 6. The carry-over Phase 0 gap: Ollama

**Superseded 2026-09-05: this gap is already closed.** Ollama is installed at `G:\Ollama` with
`OLLAMA_MODELS=G:\ollama-models`, serving `qwen3:1.7b`, `nomic-embed-text` and
`qwen3-embedding:0.6b` (~2.2 GB total, inside the 8 GB budget). `EXPERIMENTS.md` exp-001 still
says "Ollama: not installed yet" and is stale on that point - amend it in W2-T10. Phase 0 has no
open items. The reasoning below is kept because it is the right way to have made the call, and
the scope discipline at the end still governs any future model pulls.

<details><summary>Original decision (week 1 stretch, 45-minute time-box, week 3 deadline)</summary>

Why not earlier in the week:

- **Nothing this week needs it.** Lab 02 is a tokenizer-vs-cloud-usage study and lab 03 is a sampling
  study; both are cloud-only by design. The first hard dependency on Ollama is lab 08 `providers`
  (Phase 1 week 3-4) and then Phase 2 local embeddings, which is the real deadline.
- **It is a disk and time risk, not a learning risk.** ~4 GB for the binary plus 1.7 GB of models against
  ~22 GB free on G:, plus seven user environment variables and a tray-app restart that has to be got right.
  That is exactly the kind of task that eats an entire evening. Putting it on the critical path would put
  the week's actual learning behind an installer.
- **The Phase 0 exit criterion it serves is "run one small local model and know what quantized GGUF
  means"** — a 45-minute task once the environment cooperates, and one that teaches more when there is a
  lab that wants it.

Why not defer it further than week 3: it is the only open Phase 0 item, and unfinished setup debt
compounds. If it is still open at the end of week 3, it stops being a stretch item and becomes W3's
first task.

</details>

**Scope discipline for any future model pull:** pull `qwen3:1.7b` (1.4 GB) and `nomic-embed-text` (0.27 GB) only —
about 1.7 GB. `qwen3.5:4b` and `qwen3-embedding:0.6b` wait for Phase 2, when there is something to
measure them against. Do not run `llama-bench` this week.

---

## 7. Risks to finishing

| # | Risk | Evidence | Mitigation |
|---|---|---|---|
| R1 | **Gemini free-tier latency.** exp-001 measured 32.5 s for a single 65-token completion. Ten sequential calls at that rate is 5+ minutes of dead time per run, and iterating on the script multiplies it | `EXPERIMENTS.md` exp-001 | Run the *variance* study (W2-T08, 15 calls) on **Groq** (1.4-2.0 s measured), not Gemini. Keep Gemini to the ≤15 calls that genuinely need it in W2-T05/T06. Set a 60 s per-call timeout so a hang fails fast |
| R2 | **Free-tier rate limits.** Groq free is 30 RPM / 1,000 RPD / **8K TPM**; Gemini free RPM/RPD are still UNVERIFIED in `TECHNOLOGY_STACK.md` | `TECHNOLOGY_STACK.md` §1 | Sleep ≥2 s between calls. Never write an uncapped loop. Cache completions to a JSON file so re-running the analysis does not re-call the API. Opportunistically record the real Gemini limits from AI Studio into the §9 checklist while there |
| R3 | **Disk.** ~22 GB free per drive; a naive `pip install transformers` pulls torch (~2.5 GB) | `EXPERIMENTS.md` exp-000 | Use `tiktoken` (a few MB) for local counting, plus Gemini's `countTokens` API for the Gemini side. Do **not** install `transformers` or `torch` this week. Delete `labs/01-hello-llm/__pycache__` while there |
| R4 | **Tokenizer mismatch is unavoidable and may read as failure.** There is no public local tokenizer for Gemini; tiktoken's o200k is OpenAI/gpt-oss's vocabulary, not Google's | `TECHNOLOGY_STACK.md` §1 | This is the lesson, not a bug. Frame lab 02 as "how wrong is a proxy tokenizer, and which number do you budget against?" (answer: the provider's `usage`). Write that framing into `NOTES.md` before coding, so the result cannot feel like a failure |
| R5 | **Temp 0 will probably not be deterministic**, which can send Saad debugging his own code for an hour | Roadmap Phase 1 interview list names this explicitly | Predict it in `NOTES.md` *before* running W2-T08. If temp 0 gives 5 identical outputs, that is also a finding — record it and note that it does not generalise across providers or model versions |
| R6 | **Free-tier privacy.** Gemini free-tier prompts train Google's models | `TECHNOLOGY_STACK.md` §1 | The five test texts must be public-domain or synthetic. No company text, no personal data. Zero overlap with Nudge/Zortik |
| R7 | **Weekday evenings evaporate.** 8-12 h alongside a full-time job assumes ~5 usable evenings | — | Friday is already planned as zero. The cut line in §1 exists so the week degrades gracefully instead of ending with two half-finished labs |
| R8 | **OpenRouter noise.** exp-001 saw 2 of 4 free models 429 and a reasoning model return empty content with 200 completion tokens | `EXPERIMENTS.md` exp-001 | Exclude OpenRouter from both labs this week. It is a model zoo for `experiments/`, not a measurement surface. Revisit at lab 08 `providers` |

---

## 8. Exit criteria — what Saad can explain out loud on Sunday

Ask these unprompted, without notes. Each must be answerable with a **number from this week's labs**,
not a definition from the course.

1. **What a token is**, and why models operate on tokens rather than characters or words.
2. **Why the same prompt was 18 tokens on Gemini and 88 on Groq** in exp-001 — how much of that gap is a
   different BPE vocabulary and how much is chat-template and system scaffolding the API adds on your behalf.
3. **Why a local tokenizer count disagrees with `usage.prompt_tokens`**, and which of the two you budget
   and rate-limit against.
4. **What a context window is**, what consumes it (system prompt + history + tool schemas + the space you
   must reserve for the output), and how to estimate the cost of a call *before* sending it.
5. **Why output tokens dominate cost** on these models — reference the exp-001 finding that Gemini
   3.5-flash-lite cost 2.5x Groq gpt-oss-20b for the same prompt despite a more efficient input tokenizer.
6. **What temperature actually does** to the sampling distribution, and **why temperature 0 does not
   guarantee determinism** — with what the lab actually observed.
7. **When to use temp 0 vs 0.7 vs 1.2**, with a concrete example of each from Saad's own work.

If any of 1-7 is shaky, that is week 3's opening item — not a reason to slow the build.

**Explain-it-back check (per `CLAUDE.md`), to run at the end of W2-T12:**

- Why does `llm-kit` need to count tokens *before* sending, rather than reading `usage` afterwards?
- If you swapped the primary provider tomorrow, which of this week's numbers would still be true and
  which would you have to re-measure?
- Changelog Forge will chunk a 400-commit diff. Which measurement from this week tells you how big a
  chunk can be, and what is the safety margin you would leave?
