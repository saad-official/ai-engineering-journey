# Streaming LLM Responses (SSE, end to end)

**Status:** learning (drafted 2026-09-26 by the `mentor` agent, in parallel with `labs/05-stream`, before it ran)
*Why: same convention as `tool-calling.md` and `tokens-and-context-windows.md` — this note is
agent-drafted and not yet in Saad's own words. It becomes `understood` when he can explain, without
the note open, (a) why streaming does not reduce total latency, (b) the split-chunk line buffer, and
(c) every hop of the cancellation path and where it breaks — and when the Example/Implementation
placeholders below carry real lab 05 numbers.*
**Phase:** 1   **Tags:** [F], llm-fundamentals / latency / ux / cost / frontend

## Concept

A model generates its answer one token at a time no matter what — decode is serial, one forward
pass per token (`tokens-and-context-windows.md`, Architecture). A **non-streaming** call waits for
the last token and hands you the whole thing in one response. A **streaming** call (`stream=True`)
forwards each token (in practice a small group of tokens, a "chunk") the moment it is produced,
over a long-lived HTTP response, usually as **Server-Sent Events**. Streaming changes *when you
start seeing* the answer, not *how long the answer takes to exist*.

## Problem

Why does it exist? Decode speed is finite and answers are long. At 50 tokens/s, a 500-token answer
is 10 seconds of a blank screen with a spinner, which users read as "broken". Streaming turns those
10 seconds into "first words after ~0.5 s, then reading along", which is the same wait experienced
completely differently.

What breaks without it, or when you get it wrong:
- Chat UIs feel dead on every long answer, even on a fast provider.
- On a **reasoning model**, streaming only `content` still shows nothing for seconds, because the
  model is spending most of its output tokens thinking first (exp-003: 84-95% of output tokens).
- You parse the stream with `chunk.split("\n")` and it works on localhost and corrupts text in
  production, because network chunks do not align with events.
- You forget `stream_options.include_usage` and your cost ledger records every streamed call as
  zero.
- The user closes the tab, your server keeps pulling tokens from the provider, and you pay for an
  answer nobody reads.

## Mental model

**Streaming is progressive rendering for text.** Closest analogies Saad already owns:
- **React streaming SSR / Suspense.** The server does not wait for the slowest data before sending
  HTML; it flushes the shell, then streams the rest as it resolves. Total server work is the same;
  time-to-first-paint drops.
- **A video that starts before it is fully downloaded.** Same file size, same download time, but
  playback begins as soon as the first segment lands.

**Two clocks, not one.**

```
request sent
  |-- network + queue + PREFILL (reads the whole prompt, parallel) --| first chunk      <- TTFC
  |-- DECODE reasoning tokens (hidden, serial) ----------------------| first VISIBLE    <- TTFV
  |-- DECODE content tokens (serial) --------------------------------| last token       <- total
```

- **TTFC (time to first chunk)**: dominated by network, provider queueing and prefill. Grows with
  prompt length.
- **TTFV (time to first visible word)**: TTFC plus however long the model thinks before speaking.
  On a non-reasoning model TTFV ~= TTFC. On gpt-oss-20b it is `TTFC + reasoning_tokens / decode_rate`.
- **Total**: the same whether you stream or not, because decode is serial either way. Streaming
  moves the *perception* of latency, not the physics.

So the honest one-liner: **streaming optimises TTFV, not total latency, and on a reasoning model
TTFV is the number that actually decides whether the UI feels fast.**

## Architecture

```
Provider (Groq, OpenAI-compatible)
   | HTTP response, text/event-stream
   | data: {"choices":[{"delta":{"reasoning":"..."}}]}      <- reasoning field name: verify per provider
   | data: {"choices":[{"delta":{"content":"Hel"}}]}
   | data: {"choices":[],"usage":{...}}                     <- ONLY if stream_options.include_usage
   | data: [DONE]
   v
FastAPI  POST /stream   (async generator -> StreamingResponse, media_type text/event-stream)
   | re-maps provider chunks into OUR typed events, one JSON object per SSE event:
   |   data: {"type":"reasoning","text":"..."}
   |   data: {"type":"content","text":"..."}
   |   data: {"type":"usage","prompt_tokens":..,"completion_tokens":..,"reasoning_tokens":..}
   |   data: {"type":"done","finish_reason":"stop"}
   |   data: {"type":"error","message":"..."}
   | on client disconnect -> close the upstream stream (stop paying)
   v
Browser  fetch(POST, body, Authorization) -> response.body.getReader()
   | TextDecoder({stream:true}) -> string buffer -> split on blank line -> JSON.parse -> dispatch by type
   | AbortController.abort()  -> closes the TCP connection -> server sees disconnect
   v
UI: "thinking..." state (or dimmed reasoning) -> content appended -> usage/cost shown on done
```

Why the server re-maps rather than proxying the provider's chunks raw: the client should depend on
*your* event contract, not on one provider's delta shape. That is the provider-abstraction rule
(`llm-kit`) applied to the wire.

### The wire format: SSE in five rules

1. Response header `Content-Type: text/event-stream`; the connection stays open.
2. An event is one or more lines like `data: <payload>`, terminated by a **blank line** (`\n\n`).
3. The blank line is the event boundary — it is how the reader knows "this event is complete",
   because one event's payload may legally span several `data:` lines.
4. Lines starting with `:` are comments. `: ping\n\n` is the standard heartbeat to keep idle proxies
   from killing the connection (a long reasoning phase with nothing forwarded is exactly "idle").
5. Other fields exist (`event:`, `id:`, `retry:`) and are mostly for `EventSource`'s auto-reconnect.

**Why JSON with a `type` instead of raw text.** One channel has to carry five different things:
reasoning, content, usage, done, error. Raw text cannot carry an error mid-stream (a 500 status is
impossible once a 200 and headers have gone out), cannot carry usage, and cannot say "this part was
thinking". A tagged union — the same discriminated-union pattern as a Redux action or a TS
`{type: ...}` — makes the stream a typed protocol instead of a string.

**Why not `EventSource`.** It is GET-only, cannot send a body (your prompt and message history),
cannot set an `Authorization` header, and auto-reconnects — which for an LLM call means silently
*re-running and re-billing the generation*. LLM apps use `fetch` + `response.body` (a
`ReadableStream`) and parse SSE by hand, which is what lab 05's `index.html` does.

### The bug everyone writes once: split chunks

`reader.read()` returns whatever bytes the network delivered, not whole events. One read can hold
half an event; another can hold three and a half. The fix is a **line buffer**:

1. Decode bytes with **one** `TextDecoder` and `{stream: true}`, so a multi-byte UTF-8 character
   split across two reads (Urdu, emoji, lab 04's U+202F) is held back instead of turned into `�`.
2. Append to a string buffer.
3. While the buffer contains `\n\n`: cut off everything before it, that is one complete event;
   parse it; keep the remainder.
4. Whatever is left without a terminator stays in the buffer for the next read.
5. When the stream ends, flush the decoder and handle any final complete event.

Same pattern as reassembling framed messages from a TCP socket or a WebSocket that fragments.
Normalise `\r\n` to `\n` first; the SSE spec allows both.

## Example

> **Placeholder — fill from the real `labs/05-stream` run (owned by another agent; do not edit
> that directory).**

| measurement | run 1 | run 2 | run 3 | run 4 | run 5 | median |
|---|---|---|---|---|---|---|
| TTFC (s) | TBD | TBD | TBD | TBD | TBD | TBD |
| TTFV, first `content` delta (s) | TBD | TBD | TBD | TBD | TBD | TBD |
| TTFV − TTFC (s) | TBD | TBD | TBD | TBD | TBD | TBD |
| reasoning_tokens / completion_tokens | TBD | TBD | TBD | TBD | TBD | TBD |
| total, streamed (s) | TBD | TBD | TBD | TBD | TBD | TBD |
| total, non-streamed (s) | TBD | TBD | TBD | TBD | TBD | TBD |

Usage presence:

| `stream_options.include_usage` | any chunk with `usage`? | which chunk | `choices` on that chunk |
|---|---|---|---|
| omitted | TBD | TBD | TBD |
| `True` | TBD | TBD | TBD |

Cancellation: after Stop, did the server log an upstream close? How many content events had been
sent? Was `usage` ever received for the cancelled call? TBD.

### Predictions before running (written 2026-09-26, before any data)

Falsifiable. Score honestly afterwards; a prediction edited after the fact teaches nothing.

1. **On a prompt that makes gpt-oss-20b reason (the exp-003 naming prompt), TTFV − TTFC will be
   between 0.2 s and 2.0 s on Groq, and within ±40% of `reasoning_tokens ÷ observed decode rate`.**
   Reasoning: exp-003 measured reasoning at 84-95% of output tokens (e.g. 319 of 340); Groq decodes
   this model fast (hundreds of tokens/s), so ~300 reasoning tokens is a fraction of a second to a
   couple of seconds. The *ratio* TTFV/TTFC will be large (≥ 2x) even when the absolute gap is
   small. The lesson if confirmed: the gap is `tokens ÷ speed`, so the same model on a 10x slower
   provider turns the same thinking into many seconds of blank screen.
   *Falsified if:* median gap < 0.2 s or > 2.0 s, or the gap does not track reasoning tokens
   (off by more than 40%).
2. **Streamed and non-streamed total time will be within ±15% of each other (median of ≥ 5 runs
   each, same prompt, same `max_tokens`).** Reasoning: decode is serial either way; streaming adds
   only per-chunk framing overhead, which is small next to generation time.
   *Falsified if:* the medians differ by more than 15%. If streaming is clearly *faster* in total,
   suspect a confound (different output length, cold start on the first call) before believing it.
3. **Without `stream_options={"include_usage": True}`, no chunk will carry the standard
   `chunk.usage` field; with it, exactly one chunk will — the last one before `[DONE]`, with an
   empty `choices` list.** Reasoning: this is the OpenAI streaming contract that OpenAI-compatible
   providers copy.
   *Falsified if:* usage appears without the flag. Worth recording either way: if Groq sends usage
   anyway (possibly under a provider-specific key), that is a vendor extension, and code that
   relies on it breaks on the next provider.

Bonus, unscored: a cancelled stream will never deliver `usage`, because it arrives last — so the
cost of a cancelled call cannot be read from the stream itself.

## Implementation

> **Placeholder — link and summarise once `labs/05-stream` has run.**

Design decisions to record here after the run:
- Why the server emits **its own typed events** instead of forwarding the provider's chunks.
- Why the server uses an **async** generator (a sync generator runs in a threadpool, and
  cancellation reaches it late or not at all — to verify in the lab).
- How disconnect is detected (Starlette cancellation, `request.is_disconnected()`, or a failed
  write) and how fast — including whether it is noticed during a long reasoning phase when nothing
  is being written.
- Why the upstream stream is closed in a `finally`, and what the ledger records for a cancelled call.
- What the by-hand version shows about `packages/llm-kit`'s `stream()`. Read-only observations
  (2026-09-26), not changes: it yields **content only**, so reasoning is dropped and a caller
  cannot show a "thinking" state; and it records usage in a `finally`, but because the usage chunk
  arrives last, a consumer that breaks early logs **zero** usage for tokens that were billed. Both
  are candidates for the lab's Learned section and a later `llm-kit` change.

## What streaming makes harder

- **Structured output.** Half a JSON object cannot be validated. Options: don't stream it (what
  `llm-kit` does — `complete_structured` does not stream); stream it but validate and *commit* only
  at the end; or use a partial-JSON parser to render fields progressively while treating nothing as
  valid until the final parse passes.
- **Tool calls.** Arguments arrive as string fragments in `delta.tool_calls[i].function.arguments`,
  keyed by `index`. Accumulate per index and execute only after `finish_reason == "tool_calls"`.
  Lab 04's rule, sharper: a fragment can parse (`{"city":"Kara"}`) and be wrong.
- **Moderation / guardrails.** The user has read the text before you checked it. Options: check the
  input before generating; moderate in windows and retract; or buffer the last N characters before
  release. Each costs some of the latency you streamed to win.
- **Retries.** You cannot transparently retry half a response. Retrying is safe only *before the
  first event reaches the client*; after that, a retry is a visible restart the UI must handle.
- **Caching.** Cache the assembled final response, not the chunks; replay it as a fake stream if the
  UI expects one.
- **Errors.** Once `200` and headers are sent, the status code is spent. A mid-stream failure must
  be an in-band `error` event, and the client must treat a stream that ends without `done` as a
  failure, not a short answer.

## Trade-offs

| Approach | Use when | Cost |
|---|---|---|
| Non-streaming | output is parsed (JSON, tool args, classification), batch jobs, anything validated before use | user waits the full generation |
| SSE over `fetch` | chat UIs, long prose, one-way server-to-client tokens | proxy/serverless buffering pitfalls; manual parsing |
| WebSockets | truly bidirectional realtime (voice, interrupting mid-generation with new input, collaborative sessions) | stateful connections, sticky routing, own auth/reconnect protocol |
| Stream + validate at end | long structured output a user watches form | two states in the UI (rendering vs committed) |

**Why SSE over WebSockets for LLM streaming**: the traffic is one request in, one stream out. SSE is
plain HTTP — normal auth headers, normal load balancers, HTTP/2 multiplexing, a stateless
request-per-generation that scales like any other endpoint. WebSockets buy bidirectionality you
mostly do not need, at the price of stateful connections.

## Production considerations

- **Latency metrics.** Log TTFC, TTFV and total separately per call. p50/p90 of TTFV is the UX SLO
  for a chat product; total is the cost/capacity number.
- **Reasoning models in chat UIs.** Show a "thinking" state driven by reasoning events (or stream
  reasoning dimmed/collapsed), lower reasoning effort where the provider allows, or choose a
  non-reasoning model when TTFV matters more than depth. You are billed for reasoning tokens whether
  or not they are shown (exp-003).
- **Cost ledger.** Always request `include_usage`; budget against provider `usage`, never estimates
  (exp-002). A cancelled stream has no usage chunk, so log it as "billed, unknown amount" rather
  than zero, and reconcile against the provider dashboard.
- **Cancellation path.** Browser `AbortController.abort()` -> connection closes -> server notices
  (on cancellation or the next write) -> server closes the upstream HTTP stream -> provider stops
  generating. Whether the provider stops *billing* at that instant is provider-specific; measure,
  do not assume. Common breaks: a proxy that buffers the response (nginx needs `proxy_buffering off`
  or `X-Accel-Buffering: no`); gzip middleware that buffers until it has enough to compress; a
  serverless platform that buffers responses or kills long ones at a max duration; a sync generator
  that never sees the cancellation; a server that only detects disconnect on write while a long
  reasoning phase writes nothing (heartbeats or reasoning events fix both idling and detection).
- **Timeouts.** A stream needs an idle timeout (no chunk for N s) as well as a total deadline;
  a single request timeout is wrong for both.
- **Backpressure.** If the client reads slower than the provider writes, bytes buffer in the
  server. Rarely a problem at chat speeds; a real one at fan-out scale.
- **Observability.** Log the assembled final text and `finish_reason` once per call, not per chunk.
- **React Native.** Streaming `fetch` support on RN differs from browsers and has changed across
  RN/Expo versions (Expo has shipped its own streaming-capable fetch; community SSE libraries and
  XHR-progress approaches also exist). **Unverified here — check current docs before DocPilot RN.**

## Interview questions

1. *Does streaming make an LLM response faster?*
   No — it makes it *feel* faster. Decode is serial, one forward pass per token, so the last token
   arrives at the same time either way. Streaming cuts time-to-first-visible-token, which is what
   the user perceives. On a reasoning model, TTFV includes the hidden thinking, so you also need a
   "thinking" state or the win disappears.
2. *Why SSE over WebSockets for LLM streaming?*
   One request in, one stream out: SSE is plain HTTP, so auth headers, load balancers, HTTP/2 and
   stateless horizontal scaling all just work. WebSockets add stateful, bidirectional connections
   you only need for realtime two-way cases like voice or mid-generation interruption.
3. *Why not use the browser's `EventSource`?*
   GET-only, no request body, no custom `Authorization` header, and automatic reconnect — which for
   an LLM means re-running and re-billing the generation. Use `fetch` + `ReadableStream` and parse
   SSE with a line buffer.
4. *How do you stream a response that also needs to be validated?*
   Separate "rendering" from "committed". Stream for display, validate the assembled result at the
   end, and only act on it (save, execute, show as final) after validation passes. For tool calls,
   accumulate fragments and never execute before `finish_reason == "tool_calls"`. If the output is
   purely machine-consumed, do not stream at all.
5. *How do you stop paying when the user leaves?*
   `AbortController` on the client closes the connection; the server detects the disconnect and
   closes the upstream provider stream in a `finally`. Then verify each hop, because proxies,
   compression middleware, serverless buffering and sync generators each silently break it. And log
   cancelled calls as billed-unknown, since the usage chunk never arrives.
6. *Your streaming parser works locally and corrupts text in production. Why?*
   It assumes one `read()` equals one event. Network chunks do not align with SSE events or with
   UTF-8 character boundaries. Use a single streaming `TextDecoder` and buffer until the blank-line
   terminator.

## Project application

- **DocPilot RN** (Phase 2): streaming grounded answers with citations into a chat UI. Hard parts
  are exactly this note: a thinking state, citations that can only be verified once the answer is
  complete, Stop that actually stops billing, and React Native fetch-streaming support.
- **Review Radar** (Phase 3): streaming agent *steps* (tool call started, result, next thought) as
  typed events — the same tagged-union protocol, with more event types.
- **`packages/llm-kit`**: `stream()` already exists; lab 05 is the by-hand version that explains it
  and exposes its two gaps (content-only; zero usage on early break).
- **Career angle**: streaming UX, abort handling, progressive rendering and mobile networking are
  where frontend experience is a genuine differentiator in AI engineering interviews.

## Limits of what lab 05 will prove

- One provider, one model (Groq `openai/gpt-oss-20b`). Decode speed, reasoning share and usage
  behaviour are provider- and model-specific.
- Small n (≈5 per condition): detects gross effects only.
- Localhost has no proxy, CDN or serverless layer, so the cancellation path is tested only on its
  easiest route. The breaks listed above will not appear until deployment.
- The client cannot observe provider-side billing after cancellation; "we stopped paying" is
  inferred from the upstream close, not measured.

## References

- `labs/05-stream/NOTES.md` — run output (owned by another agent; link once it exists).
- `EXPERIMENTS.md` — lab 05 row to be added after the run.
- `notes/concepts/tokens-and-context-windows.md` — prefill vs decode, TTFT vs total latency.
- `EXPERIMENTS.md` exp-003 — hidden reasoning at 84-95% of output tokens on gpt-oss-20b.
- `notes/concepts/tool-calling.md`, `labs/04-tools/NOTES.md` — `finish_reason` rule; U+202F crash.
- `packages/llm-kit/src/llm_kit/client.py` `stream()` — read 2026-09-26.
- WHATWG HTML spec, Server-sent events section; OpenAI-compatible streaming docs for
  `stream_options.include_usage` — re-verify per provider at use.
