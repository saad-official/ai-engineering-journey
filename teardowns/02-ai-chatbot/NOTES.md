# Teardown 02: `vercel/ai-chatbot`

**Source:** https://github.com/vercel/ai-chatbot, commit `c2f8235` (2026-07-08, v3.1.0), shallow-cloned
to `teardowns/_src/ai-chatbot` (gitignored, never edited).
**Ladder tier:** 1 (Phase 1). Teardown 01 showed the wire protocol; this is the same protocol inside
a full product, with **persistence, auth, rate limits, artifacts and resumable streams**.
**Question:** where does conversation state live in a real chat product, who owns it, and what
happens to it when things go wrong (Stop, reload, a second tab, a limit)?
**Run:** the full Next.js app, on Gemini, at $0. Exactly **one upstream file was swapped**
(`lib/ai/providers.ts`, see `harness/providers.patch`). Postgres is PGlite behind a wire-protocol
socket (`harness/pg-server.mjs`). There is no Redis, Blob or AI Gateway. About 25 Gemini calls.

---

## 0. Before reading on: your predictions

<!-- Saad: write these BEFORE reading section 3.
  1. Teardown 01's client sent the WHOLE conversation on every request. Does a production chatbot
     do that too? If not, who holds the history, and what does the client send?
  2. You press Stop while the model is writing a long document. Does the server stop generating?
     Is anything saved? What do you see after a page reload?
  3. "Max 10 messages per hour": how many can you actually send?
-->

---

## 1. The map: what is AI, what is plumbing

About 215 files, ~2,300 lines on the AI path. The **AI path** is about 10 files:

```
app/(chat)/api/chat/route.ts      THE handler: auth -> limits -> load history -> streamText -> persist
app/(chat)/api/chat/schema.ts     zod body schema (the request contract + cost guards)
app/(chat)/actions.ts             generateTitleFromUserMessage (a second LLM call per new chat)
lib/ai/providers.ts               model resolution (Gateway upstream; Gemini in our harness)
lib/ai/models.ts                  model list + capabilities fetched from the Gateway's public API
lib/ai/prompts.ts                 system prompt, title prompt, artifact prompts
lib/ai/tools/*.ts                 getWeather, createDocument, editDocument, updateDocument, requestSuggestions
lib/artifacts/server.ts + artifacts/*/server.ts   tools that run a NESTED streamText and save a Document
lib/db/schema.ts + queries.ts     Drizzle: User, Chat, Message_v2(parts json), Document, Stream, Vote
hooks/use-active-chat.tsx         useChat config: transport shaping, onData, autoResume, approvals
```
Everything else is plumbing: auth (Auth.js credentials + guest), the sidebar/history, votes, file
upload (Vercel Blob), the editors (ProseMirror, CodeMirror, a data grid), and theming.

## 2. The one flow, traced (with what we measured)

```
use-active-chat.tsx  sendMessage({text})
  prepareSendMessagesRequest:  body = { id, message: <ONLY the new message>, selectedChatModel, ... }
                               (the whole array is sent only for a tool-approval continuation)
route.ts POST
  1  zod parse (text <= 2000 chars, uuid ids)           -> 400 on fail            [C2]
  2  checkBotId + auth() in parallel                    -> 401/403
  3  checkIpRateLimit (Redis, production only)
  4  count user messages in the last hour > entitlement -> 429                    [C3]
  5  getChatById; ownership check                       -> 403                    [C2]
     new chat? saveChat + START title LLM call (not awaited yet)
  6  history = getMessagesByChatId -> convertToUIMessages -> + new message
  7  saveMessages(user message)          <- persisted BEFORE the model runs
  8  createUIMessageStream.execute:
       write data-waiting-status (transient); 9 s health-check timer -> Gateway status API
       streamText({ model, instructions, messages: convertToModelMessages(history),
                    tools: 5, stopWhen: isStepCount(5) })        <- server-side step loop
       merge toUIMessageStream(result) into the writer
       await title -> write data-chat-title -> updateChatTitleById
  9  onEnd({messages}) -> saveMessages(assistant UIMessage, parts verbatim)       [C1]
 10  createUIMessageStreamResponse({ consumeSseStream }):
       if REDIS_URL: createStreamId(generateId()) -> createNewResumableStream     [C4: always fails]
```
A real turn (capture B): 18 SSE events, 6,817 bytes, 4.8 s. Three Gemini calls (title, step 1
tool call, step 2 answer) and two weather HTTP calls.

## 3. Findings

| # | Finding | Evidence |
|---|---|---|
| F1 | **The server owns the conversation.** The client sends one message. History is loaded from Postgres and rebuilt on every request. This is the opposite of teardown 01 and of Lab 05, and it is what makes multi-device chats, authorization and rate limits possible. The client can't forge history it never sends. | B, route.ts:167 |
| F2 | **Messages are stored as UI parts, verbatim** (`Message_v2.parts json`), not as model messages. Tool inputs/outputs, data parts, and Gemini's `thoughtSignature` all survive a reload, so teardown 01's FIX-8 problem disappears by design. The cost is that the DB schema is coupled to the AI SDK's UI types. A breaking change to UIMessage needs a data migration (the `_v2` suffixes are that scar). | C1 |
| F3 | **Tool output is unbounded and re-billed.** `getWeather` returns the whole Open-Meteo response (7 days × 24 h). That's 77% of the stream's bytes, stored in the message, and fed to the model again on **every later turn** of that chat, because history is replayed in full and there's no `toModelOutput` or `pruneMessages`. The UI card shows 6 hours. | B, get-weather.ts |
| F4 | **Two LLM calls minimum per new chat**: the title is a separate `generateText`. Artifact tools add a third: `createDocument` runs a **nested `streamText`** whose prompt is **only the title**, so the user's constraints ("900 words, with headings") never reach the model that writes the document. Context isolation keeps the main context small but drops requirements. | logs, artifacts/text/server.ts |
| F5 | **Stop doesn't stop the work.** After the client aborted mid-document, the nested generation ran to completion (5,608 chars, saved about 11 s later, billed). The assistant message was **never** saved, so the Document is orphaned (no `chatId` column). | C5 |
| F6 | **Resumable streams are dead twice over.** (a) The resume endpoint `GET /api/chat/[id]/stream` was replaced by `return 204` in upstream `9d5d8a3` (2026-01-15), yet the client still calls `resumeStream()` on load and the POST still tries to publish. (b) Even before that, the POST could never publish: `generateId()` gives `"o7MR2KI5QSpHkFem"`, the `Stream.id` column is `uuid`, Postgres rejects it (22P02), and a try/catch labelled "non-critical" hides it. Net effect after F5: reload shows a question with no answer. | A, C4, C6 |
| F7 | **The rate limit is off by one** ("10/hour" allows 11). The check reads the count before inserting. A concurrent burst **didn't** get past it here, but PGlite serializes queries, so that's not proof. The robust shape is one atomic `INSERT ... RETURNING count` or a Redis `INCR` (which the IP limiter already does). | C3 |
| F8 | **No cost visibility.** Usage isn't sent to the client, isn't stored, and isn't logged. Production relies on OpenTelemetry (`telemetry.isEnabled` only in prod) and the Gateway dashboard. Locally you can't answer "what did this chat cost?". | B |
| F9 | **`timestamp without time zone` with two writers.** App-written times are UTC (JS Date); `defaultNow()` columns are the DB session's zone. They agree only if the server runs in UTC, so moving to a non-UTC DB silently shifts the rate-limit window. | C3 note |
| F10 | **Dead feature paths**: a full tool-approval flow (route.ts:137-165, `sendAutomaticallyWhen`, `addToolApprovalResponse`) but **no tool sets `needsApproval`**; and `getStreamIdsByChatId` with no caller. Templates accumulate half-features. | grep |
| F11 | **Guests are real users.** Every new browser creates a `User` row (`guest-<timestamp>`, `isAnonymous=false`) that is never cleaned up. That's fine for a demo and a growth problem in production. | C1 |

**What they do well (steal these):**
- **Request contract with cost guards in the schema**: max 2,000 chars per text part, an
  allow-listed model id (unknown → default), image types limited to jpeg/png.
- **Authorization before work**: the ownership check (403) runs before any LLM call or DB write.
- **Transient data parts** (`transient: true`) for UI-only state such as waiting/health status:
  sent to the client and never persisted. The rule of thumb is to persist what the conversation
  needs and stream what the UI needs.
- **Graceful degradation**: no Redis means no IP limit and no resume, but the app still works.
  Capabilities are fetched with a 24 h cache, and model health with a 60 s cache plus a 9 s
  "still waiting" timer.
- **Generative UI**: a tool part type (`tool-getWeather`) maps to a React component (the weather
  card). The model's tool call *is* the UI.

## 4. Diff against our labs and teardown 01

| Concern | Lab 05 / teardown 01 port | ai-chatbot |
|---|---|---|
| Who holds history | client sends everything | server (Postgres); client sends 1 message |
| Persistence | none | UIMessage parts as JSON, user msg before, assistant msg in `onEnd` |
| Tool loop | hand-written, MAX_STEPS 4 | `streamText` `stopWhen: isStepCount(5)` |
| Provider state (signatures) | carried by hand (FIX-8) | free, because parts are stored verbatim |
| Usage / cost | in `finish` metadata, logged | not exposed (OTel in prod only) |
| Stop / disconnect | close upstream on disconnect (Lab 05) | work continues; assistant msg may be lost |
| Abuse controls | prompt length cap | zod caps + per-user hourly count + IP limit + BotID |

## 5. If this were our product: the fixes, in priority order

1. **Persist on abort.** Save the partial assistant message on abort/error, not only in `onEnd`.
   Give `Document` a `chatId` and `messageId`. Pass the abort signal into the nested generation.
2. **Bound tool output for the model** (`toModelOutput`: current temperature + 6 hours), and keep
   the full payload only for the UI. Prune old tool outputs from replayed history.
3. **Pick one resume story**: either restore the GET handler with `crypto.randomUUID()` stream
   ids, or delete `useAutoResume` and the `consumeSseStream` publish. A half-feature is worse than
   none.
4. **Atomic rate limit**, `>=` not `>`.
5. **Record usage per message** (a `usage` json column, or `messageMetadata`) so cost per chat is a
   query, not a dashboard.
6. `timestamptz` everywhere.

## How to reproduce

```bash
RUN_DIR=<a dir with ~1 GB free> bash teardowns/02-ai-chatbot/harness/setup.sh
cd "$RUN_DIR"
node pg-server.mjs ./.pglite 5433          # terminal 1
npx tsx lib/db/migrate.ts                  # once
npm run dev -- --port 3091                 # terminal 2 (or preview_start "teardown-02-chatbot")
node probe-stream-id.mjs                   # F6b
node sql.mjs 'select role, length(parts::text) from "Message_v2"'
```
Windows gotchas, both hit here: (1) run pnpm from PowerShell, not Git Bash, or the links point
at an MSYS `/tmp` path Node can't follow. (2) Turbopack didn't resolve pnpm's junctions in this
setup, so `.npmrc` gets `node-linker=hoisted`.

## Explain it back

1. ai-chatbot sends one message and teardown 01 sent the whole array. List two things the
   server-owned design makes possible and one thing it makes harder.
2. Walk through F5 + F6: the user presses Stop, then reloads. What happens to the tokens, the DB
   rows and the screen? Which single fix from section 5 removes most of the damage?
3. Why is storing UIMessage `parts` (not model messages) in the DB both the reason provider
   signatures "just work" and a migration risk?
4. The weather tool's output is about 5 KB. Over a 10-turn chat that asked about the weather once,
   roughly how many times is that 5 KB billed as input, and what two mechanisms would cut it?
