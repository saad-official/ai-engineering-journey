# Lab 05 notes: streaming

**Question.** "Streaming makes it faster": faster at *what*? Labs 01-04 waited for the whole
answer. Here the same completion goes out three ways (terminal, a FastAPI SSE endpoint, and
a no-build browser page reading `fetch` + `ReadableStream`) and each layer gets timed. Three
things get measured instead of taken on faith:

1. **First byte vs first visible token.** gpt-oss-20b is a reasoning model, and Groq streams
   its hidden reasoning in a non-standard `delta.reasoning` field *before* any `delta.content`.
   So "the stream started" and "the user can read something" are two different moments. The
   gap between them is the headline number of this lab.
2. **Total time, streamed vs not.** Does streaming cut *total* latency, or only *perceived*
   latency?
3. **Does usage survive streaming?** Without `stream_options={"include_usage": True}`, the
   OpenAI spec sends **no usage at all** on a stream. A cost ledger that reads `usage` then
   records $0 for every streamed call and never complains.

No framework. The Vercel AI SDK (TECHNOLOGY_STACK.md, Phase 2) does all of this for you:
`useChat` *is* a fetch + stream reader + SSE parser. This lab builds that by hand once,
following CLAUDE.md rule 6. `packages/llm-kit`'s `stream()` is the reusable version and is
deliberately **not** imported here.

**Prediction, written before the run** (R5: if it turns out wrong, leave it wrong and say so):

<!-- Saad: write these BEFORE `uv run main.py`. Numbers, not adjectives.
     - Groq: time to first chunk ≈ ___ s, time to first VISIBLE token ≈ ___ s.
     - Gemini (hides its reasoning): will its first chunk be early or late? Why?
     - Median total time, streamed vs non-streamed: which one wins, and by how much?
     - Without include_usage: does Groq return usage anywhere? Does Gemini?
     - Mean visible characters per content chunk: ___ (a token is ~4-5 chars of prose). -->

**Setup.** Provider is **Groq** `openai/gpt-oss-20b` by default (fast, and it *streams* its
reasoning, which makes the gap visible). `--provider gemini` (`gemini-3.5-flash-lite`) is
the contrast case: it reasons without streaming the reasoning, so the wait should move
in front of the first chunk instead. `MAX_TOKENS=1536`. Lab 03 lost a whole run at 256, and
here a budget that runs out mid-reasoning produces a stream that is *all* reasoning with no
visible token at all. `temperature=0` as an **experimental control** (it holds output length
steady so section C compares the transport, not answer length), not as a product choice.

| Measurement | What it is | What it isolates |
|---|---|---|
| headers in | `create(stream=True)` returns | the HTTP response opening: status + headers, no body yet. A non-streamed `create()` blocks here for the whole generation |
| first chunk, any kind | first `ChatCompletionChunk` of any shape | queue + **prefill** (reading the prompt, parallel). Often a role-only chunk with no text |
| first reasoning chunk | first non-empty `delta.reasoning` | the model has started **decoding**, but it is decoding its hidden chain of thought |
| **first VISIBLE token** | first non-empty `delta.content` | what a user actually waits for: prefill **+ all of the reasoning decode**. On a reasoning model, this is the real "TTFT" for UX |
| gap: first chunk → visible | the two above subtracted | hidden reasoning, timed live. The headline number |
| total | last chunk received, stream closed | prefill + the whole decode. Governed by output tokens, not by streaming |
| chunks / chars per chunk | counts by kind; visible chars per content chunk | the granularity of a stream: roughly one token per chunk, a few characters each. It is also why UI updates must be cheap |
| decode rate | `completion_tokens / (total − first chunk)` | serial decode speed, tokens/s. The number that bounds total latency |
| §B usage | the same call with `include_usage` **off** | whether the provider sends usage anyway (standard `chunk.usage`? Groq's `x_groq.usage` extension?) or leaves your ledger blind |
| §C compare | N streamed + N non-streamed, **interleaved** S,N,S,N | total and first-visible medians (with min–max). For a non-streamed call, first visible **=** total. Interleaving spreads provider load drift across both groups |
| `finish_reason` | from the last choice-bearing chunk | `length` = budget ran out (maybe during reasoning). **None** = the stream ended with no reason, meaning the connection dropped mid-answer, *after* the user already read half of it |

**Three streaming-only traps the code handles, each commented where it happens:**

- **An HTTP timeout is not a deadline on a stream.** httpx's read timeout is the maximum
  silence *between two bytes*. A stream that sends a chunk every 50 s never times out.
  `main.py` sets a per-read timeout for dead connections *and* a wall-clock
  `STREAM_DEADLINE_S` checked inside the loop for slow ones.
- **`max_retries=0` matters more here.** A retry after the first chunk replays the whole
  answer from the top into a terminal or UI that has already shown half of it. Retrying a
  stream is only safe before the first byte.
- **`time.monotonic()` is too coarse on this machine.** On Windows with Python 3.12 it is
  `GetTickCount64`, which ticks every **15.625 ms**. That is coarser than the gap between two
  chunks, so first chunk and first reasoning chunk would collapse into one number. All timing
  uses `time.perf_counter()` instead. (Found by the offline smoke test, before any real run.)

**No cache**, and here the reason is absolute: timing *is* the experiment. A cached response
has a time-to-first-token of zero. `runs/<UTC>-<provider>.json` is provenance only: per-run
timestamps, chunk counts, usage (and which chunk carried it), finish_reason, content. Pacing
is `rate_limit()` from labs 03/04, unchanged: it runs before each call, on the error path too,
and never after the last. It paces from the call's *start*, which is correct for a stream,
because the limit counts requests, not seconds spent streaming.

### Layer 2 and 3: the server and the page

```
uv sync                                        # first time only (fastapi, uvicorn)
uv run uvicorn server:app --port 8765          # then open http://localhost:8765
LAB05_PROVIDER=gemini uv run uvicorn server:app --port 8765   # (PowerShell: $env:LAB05_PROVIDER="gemini"; ...)
```

The key never leaves the server. The page talks only to `/stream` on the same origin, so
it needs no CORS setup either. SSE events (one JSON object each, framed `data: <json>\n\n`):

```
start      {type, provider, model}
reasoning  {type, text}
content    {type, text}
usage      {type, prompt_tokens, completion_tokens, reasoning_tokens}
done       {type, finish_reason, server_ms: {first_chunk, first_content, total}, chunks}
error      {type, message}
```

**Why JSON per event instead of raw text:** the blank line (`\n\n`) *is* the SSE event
terminator, and a three-paragraph answer contains `\n\n`. Sent raw, the first paragraph break
would end the event. `json.dumps` turns every newline into the two characters `\n`.

**Why not `EventSource`:** GET only (the prompt needs a body), no custom headers (no auth
token), and it auto-reconnects, which for an LLM call means paying for the whole generation
again.

**The split-chunk buffer (index.html):** the network cuts bytes wherever it likes, so one
`reader.read()` can hold three events or half of one. The parser appends each read to a
buffer, cuts complete events off the front at each `\n\n`, and keeps the unfinished tail for
the next read. `TextDecoder` with `{stream: true}` handles the same problem one level down
(a UTF-8 character cut in half). The page runs a self-test on load that cuts a sample at
every byte position. The meta line under the answer reports **"events split across two
reads"** for a live run, so you can see whether it happened.

**Disconnect:** Stop calls `AbortController.abort()`, which closes the browser's connection.
The server checks `await request.is_disconnected()` once per chunk, and it is also cancelled
by Starlette if the client leaves while the provider is silent. Both paths end in a
`finally` that closes the upstream connection to the provider. That close is the only "stop
generating" signal an HTTP API has. Tokens generated after the user leaves are still billed.

---

## Results (run 1, 2026-09-26)

Command: `uv run main.py` (Groq), then `uv run main.py --provider gemini --skip-compare`.
Browser: `uv run uvicorn server:app --port 8765`, one Stream click, one Stop click at ~1 s.
Transcripts: `runs/20260926T075137-groq.json`, `runs/20260926T075310-gemini.json`.
No runs thrown away.

### A. One streamed call: where the time goes

| clock | Groq gpt-oss-20b | Gemini 3.5-flash-lite |
|---|---|---|
| first chunk (any kind) | 1.32 s | 1.48 s |
| first reasoning chunk | 1.32 s | never |
| **first VISIBLE token** | **1.52 s** | 1.48 s |
| total | 1.74 s | 2.55 s |
| gap: first chunk -> visible | **0.19 s** | 0.00 s |
| chunks | 405 (111 reasoning, 291 content) | **12** (11 content) |
| visible chars per content chunk | median 4, max 14 | ~23 tokens per chunk |
| decode rate after first chunk | ~982 tok/s | ~241 tok/s |
| usage | in 91 / out 412 (112 reasoning) | in 21 / out 259 |

Groq's reasoning phase was real (112 tokens, 550 chars) but Groq decodes at ~980 tok/s,
so it cost the user only **0.19 s** of blank screen. The same 112 reasoning tokens at
Gemini's ~241 tok/s would be ~0.46 s; at a 50 tok/s provider, over 2 s.

**The +71 again:** the same prompt billed 91 input tokens on Groq and 21 on Gemini. 91 - 21
= 70, which is exp-002's constant Groq chat-template overhead reproduced in a different lab.

### B. Usage in streams

| | include_usage=True | include_usage=False |
|---|---|---|
| **Groq** `chunk.usage` | present (separate final chunk, `choices=[]`) | **present** (on the last content chunk) |
| Groq `x_groq.usage` | present | present |
| **Gemini** `chunk.usage` | present | **ABSENT** |

**The trap is provider-dependent.** On Groq you cannot trigger it; on Gemini a streamed call
without `include_usage` reports nothing at all, and a ledger reading `usage` records $0 -
silently. Testing only Groq would have concluded the trap does not exist.

### C. Streamed vs non-streamed (Groq, N=3 each, interleaved S,N,S,N,S,N)

| | first visible token (median) | total (median) | completion tokens (median) |
|---|---|---|---|
| streamed | **1.09 s** (0.64-1.10) | 1.49 s (1.39-1.50) | 412 |
| non-streamed | 1.25 s (0.93-1.79) (= total) | **1.25 s** (0.93-1.79) | 412 |

Streaming improved perceived latency by only **0.16 s**, and total time was **0.24 s
(+19%) slower** - but n=3 with overlapping ranges (non-streamed spans 0.93-1.79) is noise,
not a finding. What IS a finding: on a ~1000 tok/s provider with a ~400-token answer, the
whole response takes ~1.3 s, so there is very little latency for streaming to hide.
Streaming's value scales with generation time: long answers, slow providers, reasoning.

### Browser (server running, one Stream click, one Stop click)

**Stream (complete):**

| clock | browser | server |
|---|---|---|
| response headers | 0.06 s | |
| first byte (the server's own `start` event) | 0.16 s | |
| first reasoning | 0.90 s | 0.87 s |
| first VISIBLE token | 1.58 s | 1.56 s |
| total | 2.16 s | 2.14 s |

Browser minus server on first visible token: **0.02 s**. Usage event received: in 91 / out
356 (112 reasoning). `finish_reason=stop`.

**`network reads 349 | SSE events 349 | events split across two reads 0`.** On localhost
every `read()` delivered exactly one complete event. This is *why* a naive
`chunk.split("

")` parser passes every local test: localhost never splits an event. The
buffer only earns its keep behind real networks and proxies - which is where it is never
tested. The page's own self-test (all 156 byte split points) is the only thing that
exercised it.

**Stop at ~1 s:**

- page: `stopped by you` · 195 SSE events received · **`usage: none received (a stopped
  stream never gets the final usage event)`**
- server log: **`client disconnected after 263 chunks - closing upstream`** via the
  *checked* path (`request.is_disconnected()`), `usage=None`

The cancellation chain worked end to end. But **263 - 195 = ~68 chunks were pulled from the
provider after the user had stopped reading**, before the server noticed - on localhost,
with no proxy. Behind nginx with default buffering, or on a platform that buffers
responses, that number grows with the whole answer. And because usage arrives last, the
stopped call's cost is unknowable from our side: those tokens were billed and the ledger
has no row for them.

---

## Learned

<!-- Saad's own words. Do not paraphrase the script's output back: the script already
     printed the numbers, and this section is what they MEAN. One or two sentences each:

     - Section A gave you three timestamps: first chunk, first reasoning, first VISIBLE
       token. Map each one onto prefill and decode (tokens-and-context-windows.md). Then:
       if a PM says "our TTFT is 200 ms" about a reasoning model, what question do you ask
       back, and which of your numbers answers it?

     - Section C: did streaming change the TOTAL time? Use your medians and the min-max
       spread, and say whether N=3 can even tell. If total did not move, what exactly did
       streaming buy the user, and name one feature where that is worth nothing (hint:
       anything whose output must be validated before anyone sees it).

     - Section B: if include_usage had been off in production for a month, what would your
       cost dashboard have shown for streamed calls, and how would you have noticed? And
       where does a STOPPED stream's cost go, given that usage arrives in the last chunk?

     - The split-chunk buffer: explain in two sentences why the naive "split every read on
       \n\n" version works on localhost and breaks in production. Then name the second,
       lower-level version of the same bug that TextDecoder's {stream: true} prevents.

     - Required, concrete and from YOUR work (frontend/mobile, not a textbook): one screen
       you would stream into and one you would NOT, and what decides it. Say how you would
       render reasoning there (hide it, collapse it, show a "thinking..." state), and what
       React Native would need that this page did not (think: no ReadableStream on older
       RN fetch). -->

## Open questions for later labs

<!-- Carry at least one forward. Candidates:

     - Does the provider actually STOP generating when we close the connection, or does it
       finish and bill the whole answer anyway? Nothing in this lab can observe it from our
       side. Compare completion_tokens on the provider dashboard for a stopped call vs a
       full one.

     - gpt-oss on Groq accepts `reasoning_effort` (low / medium / high). How much of the
       first-visible-token gap does "low" remove, and what does it cost in answer quality?
       That is the direct lever on this lab's headline number.

     - Gemini hides its thinking. Does `include_thoughts` in its OpenAI-compatible
       extra_body make it stream reasoning like Groq does, and does its first chunk then
       move earlier?

     - Streaming vs validation: llm-kit's complete_structured() does not stream. Can a
       partial-JSON parser stream a structured object safely, and what can be shown before
       the schema check passes?

     - Behind a real host (Render, PaaS proxies, Cloudflare), does X-Accel-Buffering: no
       survive, or does the stream arrive in one lump? Deploying this server once answers it.

     - Vercel AI SDK 7's UI message stream protocol: how different is it from this
       schema, and what would server.py have to emit for useChat to consume it directly? -->
