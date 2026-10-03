# Teardown 01: `vercel/ai` → `examples/next-fastapi`

**Source:** https://github.com/vercel/ai/tree/main/examples/next-fastapi, commit `2136151`
(2026-10-03). Sparse-cloned into `teardowns/_src/vercel-ai`, which is gitignored and never
edited.
**Ladder tier:** 1 (Phase 1: streaming + tools). It sits directly on top of Lab 04 (tools) and
Lab 05 (stream).
**Question:** how does a real, Vercel-maintained Python backend feed `useChat`? In other words,
what wire format lets one stream carry text, tool calls and tool results?
**Time / cost:** one session. About 20 Gemini calls in total, under $0.003 at paid rates and $0
on the free tier.

---

## 0. Before reading on: your prediction

<!-- Saad: answer before reading section 3. Lab 05 sent {"type": "content", "text": ...}.
     How would YOU let one stream carry text AND "the model called get_weather(Lahore)" AND
     "the tool returned 31°C", so React can render each as a different component?
     Write it down, then compare with the two designs in section 3. -->

---

## 1. What the example is

It is three demo pages and one Python endpoint. It is not an app: there's no database, no auth
and no history.

```
examples/next-fastapi/
├── app/(examples)/01-chat-text/page.tsx       useChat + TextStreamChatTransport  (?protocol=text)
├── app/(examples)/02-chat-data/page.tsx       useChat, default transport, renders tool parts
├── app/(examples)/03-chat-attachments/page.tsx useChat + files
├── next.config.ts                             rewrites /api/* -> http://127.0.0.1:8000 in dev
└── api/
    ├── index.py          THE backend: POST /api/chat, stream_text() generator, ~130 lines
    └── utils/
        ├── prompt.py     ClientMessage model + convert_to_openai_messages()
        ├── tools.py      get_current_weather() (returns a random number)
        └── types.py      ClientAttachment, ToolInvocation
```

**The architecture idea worth keeping:** `next.config.ts` rewrites `/api/*` to the FastAPI
process in development, and to a Vercel Python function in production. The browser only ever
calls its own origin, so you get no CORS and no API key in the browser. The Python service is
an implementation detail behind a Next.js URL. That is the same "server in the middle owns the
key" rule as Lab 05, done with a rewrite instead of serving static files from FastAPI.

## 2. The one flow, traced (as designed)

```
02-chat-data/page.tsx
  sendMessage({text})                          useChat appends a UIMessage, status -> submitted
  -> DefaultChatTransport.sendMessages()       POST /api/chat {id, messages, trigger, messageId}
  -> next.config.ts rewrite                    -> 127.0.0.1:8000/api/chat
index.py  handle_chat_data()                   Pydantic: Request{messages: List[ClientMessage]}
  -> convert_to_openai_messages()              UI shape -> OpenAI shape (tool invocations split
                                               into assistant{tool_calls} + tool{} messages)
  -> StreamingResponse(stream_text(...))       sync generator; Starlette runs it in a threadpool
stream_text(protocol="data")
  client.chat.completions.create(stream=True, tools=[weather])
  for chunk: text delta        -> yield '0:"..."\n'
             tool-call delta   -> accumulate id/name/arguments
             finish=tool_calls -> yield '9:{call}'   then RUN the tool, yield 'a:{call+result}'
             choices == []     -> yield 'd:{finishReason, usage}'
<- header x-vercel-ai-data-stream: v1
useChat parses lines -> message.parts -> page renders text / `toolName({...})` blocks
```

## 3. The wire formats: three designs for the same problem

Here is the same assistant turn ("the model called the weather tool, then answered") in each
format.

**Lab 05, by hand.** SSE, one JSON object per event, `type` field:
```
data: {"type":"content","text":"The sky"}
```
This works for text only. There is no id, so it can't say which block a delta belongs to, and
it has nothing for tools.

**AI SDK 4 "data stream" (what `index.py` emits). Newline-delimited `<code>:<json>`:**
```
9:{"toolCallId":"call_1","toolName":"get_current_weather","args":{"location":"Lahore","unit":"celsius"}}
a:{"toolCallId":"call_1","toolName":"get_current_weather","args":{...},"result":{"temperature":31,...}}
0:"It is 31°C in Lahore."
d:{"finishReason":"stop","usage":{"promptTokens":272,"completionTokens":38}}
```
It's compact, and the one-character prefix is the discriminator. It isn't SSE, so it's not
debuggable with standard tooling, and there's no notion of "a text block starts / ends".

**AI SDK 5+ "UI message stream" (what today's `useChat` expects).** SSE again, typed JSON
parts, and explicit lifecycles:
```
data: {"type":"start","messageId":"msg-40c3447630c7"}
data: {"type":"start-step"}
data: {"type":"tool-input-start","toolCallId":"call_1057582","toolName":"get_current_weather"}
data: {"type":"tool-input-delta","toolCallId":"call_1057582","inputTextDelta":"{\"location\":..."}
data: {"type":"tool-input-available","toolCallId":"call_1057582","toolName":"get_current_weather","input":{...}}
data: {"type":"tool-output-available","toolCallId":"call_1057582","output":{"temperature":31,...}}
data: {"type":"finish-step"}
data: {"type":"start-step"}
data: {"type":"text-start","id":"text-1"}
data: {"type":"text-delta","id":"text-1","delta":"The current weather in Lahore is 31 degrees Celsius."}
data: {"type":"text-end","id":"text-1"}
data: {"type":"finish-step"}
data: {"type":"finish","finishReason":"stop","messageMetadata":{"usage":{...},"costUsd":0.0001766}}
data: [DONE]
```
(This is the real output of our port; the full bytes are in `captures/J-v5-usechat-tool.txt`.)

**Why Vercel moved from v4 to v5, and why it's the same lesson as Lab 05:**
- **Start/delta/end with an `id`.** Several blocks can be open at once (reasoning and text,
  two parallel tool calls), and the client knows which block each delta belongs to. A stream is
  a set of interleaved block lifecycles, not one string.
- **Tool input streams too** (`tool-input-delta`). The UI can show "calling
  get_weather(Lah…" while the arguments are still being generated. v4 could only show a tool
  call once it was complete.
- **Steps** (`start-step` / `finish-step`). One user turn can be model → tool → model. The
  client has to know where one model call ends and the next begins.
- **SSE + JSON.** You get standard framing, newline-safe JSON encoding, and an `error` part.
  These are exactly Lab 05's reasons, in its `sse()` docstring.
- **`[DONE]`.** An explicit terminator, so a dropped connection can't be mistaken for a
  finished answer.

## 4. What actually happens when you run it (findings, each with a capture)

I ran their `api/index.py` **unmodified**, via `run_original.py`, which swaps only the client
for Gemini and overrides the model name. I sent requests two ways: by hand in the legacy shape
the backend was written for, and through the real `ai@7.0.127` client code
(`client-check/consume.mjs` uses `DefaultChatTransport` + `readUIMessageStream`, which is
`useChat` minus React).

| # | Probe | Result | Capture |
|---|---|---|---|
| F1 | Real `useChat` request body → original | **422.** `useChat` sends `messages[].parts`; the backend requires `messages[].content: str`. Every message fails validation. | `F-…`, `G-…` |
| F2 | Legacy body, `?protocol=data`, tool prompt | **200 OK, empty body, no error logged.** The worst failure mode: the spinner just stops. | `B-…` |
| F3 | Why F2 is empty, from the raw Gemini chunks | Two independent bugs. **(a)** Gemini sends the whole tool call in **one** chunk (id + name + complete args, and no `index`). The code only appends arguments on *later* chunks, so it stores `""` and loses them. **(b)** Gemini ends with `finish_reason: "stop"`, not `"tool_calls"`, and tool parts are only emitted on `"tool_calls"`. Fixing (a) alone would still print nothing. | `C-…` |
| F4 | Legacy body, `?protocol=text`, tool prompt | The response body is the literal string **`None`**: `"{text}".format(text=delta.content)` on a tool-call chunk whose `content` is `None`. | `E-…` |
| F5 | Usage on Gemini | With `include_usage`, Gemini puts a **running total on every chunk** and never sends OpenAI's final `choices: []` chunk. The original waits for `choices == []` to emit `d:`, so on Gemini there's never a finish part and never usage. It also never sets `stream_options` at all, so on OpenAI too there's no usage chunk (Lab 05, exp-019). | `D-…` |
| F6 | Legacy `0:`/`d:` bytes fed into today's client parser | **Nothing and no error**: `assistantMessage: null, error: null`. The SSE parser ignores lines that aren't `data:`. A protocol mismatch fails silently. | `H-…` |
| F7 | Tool loop | Even when it works (on OpenAI), the turn ends at the tool result. There's no second model call, so the user sees `get_current_weather({...})` and **no worded answer**. In AI SDK 4 the *client* re-submitted (`maxSteps`); the v5 page doesn't configure `sendAutomaticallyWhen`, so nothing would. | read of `index.py` |
| F8 | Gemini `thought_signature` | Each Gemini tool call carries `extra_content.google.thought_signature`. Sending the tool result back **in the same turn without it → HTTP 400** ("Function call is missing a thought_signature"). Stripping it from a **previous** turn's call was tolerated. | `L-…`, `K-…` |

**The root cause of most of this:** the frontend was upgraded with the SDK (it imports
`TextStreamChatTransport`, `isStaticToolUIPart`, `message.parts`, which are all v5+), and the
Python backend wasn't. In a monorepo the TypeScript side is type-checked against the SDK on
every build. The Python side has no contract test, so nothing turned red. **A wire protocol
between two languages is an API with no compiler. Only a test that crosses the boundary
protects it.**

Second root cause: the "OpenAI-compatible" assumption. The code is correct for OpenAI's chunk
pattern and wrong for Gemini's. F3, F5 and F8 are all the same lesson as exp-019's usage
finding: compatible means "same shape on the happy path", not "same behaviour".

## 5. The port: `server_v5.py`

It's the same endpoint, rewritten to speak the UI message stream. Each fix is tagged in the
code (`FIX-n`):

| Fix | What | Why (finding) |
|---|---|---|
| 1 | Accept `UIMessage.parts`, `extra="allow"` | F1. Lenient on purpose: the SDK adds part types in minor versions |
| 2 | Emit SSE UI message chunks + `x-vercel-ai-ui-message-stream: v1` + `[DONE]` | F6 |
| 3 | Assemble tool calls by `index`; fall back to "new id = new call" | F3a. Handles OpenAI's trickled args and Gemini's all-at-once |
| 4 | "Tools were called" = calls collected, not `finish_reason` | F3b |
| 5 | Server-side step loop, `MAX_STEPS = 4` | F7. Lab 04's loop, now streaming |
| 6 | `include_usage` + last-usage-wins per step, summed across steps | F5 |
| 7 | Only non-empty `content` becomes text | F4 |
| 8 | Echo `extra_content` (thought signature) on the next request; also round-trip it through the UI as `callProviderMetadata` | F8 |
| 9 | `AsyncOpenAI` + disconnect check + `error` part | Lab 05 |
| 10 | Bad JSON args / tool exceptions → `tool-input-error` / `tool-output-error`, sent back to the model | Lab 04, F-sections |

**Verified with the real client:** plain text (`I-…`), a tool turn with a worded final answer
in 2 steps (`J-…`), and a 2-turn conversation where turn 2 calls the tool again and compares
(`K-…`). The cost is in the message metadata: $0.00018 for the tool turn, and the server logs
`in=272 out=38`.

**Not done (honest limits):** `?protocol=text` and attachments weren't ported. There's no
automated test of `to_openai_messages`. The disconnect path wasn't exercised in this teardown
(Lab 05 measured it). And I didn't run the actual Next.js pages: that needs `pnpm install` of
the whole monorepo plus building every SDK package. I didn't measure the size, but it's several
GB at a guess, on a disk with 6.4 GB free. The `ai` package's transport +
`readUIMessageStream` is the code `useChat` runs; React only re-renders `parts`.

## 6. Diff against our own labs

| Concern | Lab 05 | Their example | Port |
|---|---|---|---|
| Framing | SSE + JSON `type` | custom `code:json` lines | SSE + JSON `type` (= Lab 05's idea, standardised) |
| Block identity | none | none | `id` per text block, `toolCallId` per tool |
| Tools in stream | no | after-the-fact only | input streams, then output |
| Multi-step | n/a | client-driven (v4), broken (v5) | server-driven loop |
| Usage | `include_usage`, provider check | never requested | requested, summed across steps |
| Async / disconnect | AsyncOpenAI, checked | sync generator, unchecked | AsyncOpenAI, checked |
| Errors after 200 | `error` event | exception kills the stream | `error` part |
| Provider quirks | `read_chunk()` normalises | assumes OpenAI | normalises tool calls, usage, signature |

**What they did better than our labs:** the rewrite-based topology (section 1), and the `id`
on every block. Lab 05's event schema can't represent two concurrent blocks. Copy that into
`llm-kit`'s `stream()` design.

## 7. Things to steal

1. Put block `start`/`delta`/`end` with ids in every streaming protocol you design.
2. Never decide control flow from `finish_reason` alone. Derive it from what you actually
   received.
3. Use a contract test across any language boundary. Here that's one Node script that pushes a
   real `useChat` request through the backend and asserts a non-empty assistant message. It
   would have caught F1, F2, F6 and F7 the day they were introduced.
4. Treat provider metadata (signatures, cache ids) as part of the conversation state. Carry it
   through the UI and back.

---

## How to reproduce

```bash
cd teardowns/01-next-fastapi && uv sync && (cd client-check && npm install)
uv run uvicorn run_original:app --port 8000      # their code, on Gemini
uv run uvicorn server_v5:app --port 8001         # the port
node client-check/consume.mjs <name> http://127.0.0.1:8001/api/chat data "What is the weather in Lahore in celsius?"
node client-check/multiturn.mjs http://127.0.0.1:8001/api/chat
uv run python probe_chunks.py "<prompt>" [--include-usage]   # raw provider chunks
uv run python probe_signature.py                              # F8
```
The source clone: `git clone --depth 1 --filter=blob:none --sparse https://github.com/vercel/ai.git teardowns/_src/vercel-ai`
then `git -C teardowns/_src/vercel-ai sparse-checkout set examples/next-fastapi`.

## Explain it back

1. F2 returned `200 OK` with an empty body. Why is "200 + empty" worse than a 500, and which
   *two* bugs both had to be fixed before any tool part could appear?
2. Why does the UI message stream have `start-step`/`finish-step`? What would the UI get wrong
   on the weather question without them?
3. The port loops on the server; AI SDK 4 looped on the client (`maxSteps`). Name one
   advantage of each. Which one lets you enforce a cost budget, and why?
4. Gemini returns 400 without the `thought_signature` in the same turn but tolerates it on an
   older turn. Where in *your* future apps does provider-specific state need to survive a
   round-trip through the browser?
