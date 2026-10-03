# Conversation State and Persistence (who owns the chat)

**Status:** learning
**Phase:** 1 → 4   **Tags:** [F], architecture, streaming, cost

## Concept

A chat is a growing list of messages, and an LLM API is stateless: every call must be sent the
whole relevant history. "Conversation state" is the decision of **where that list lives** (client
or server), **in what shape** (UI parts vs model messages), and **when it is written**
(before, during, after generation). The decision drives cost, security, multi-device behaviour,
and what survives Stop, reload and crashes.

## Problem

Labs 04-05 and teardown 01 kept history in the client and posted the whole array each time. That
is simple, and it fails in three ways at product scale:
- **Trust:** the client can forge history, including fake assistant turns or fake tool results.
  That's prompt injection with extra steps.
- **Durability:** close the tab and the chat is gone. Another device can't see it.
- **Control:** the server can't rate-limit, bill or audit a conversation it never stores.

## Mental model

Think of it like React state vs a server cache. The **server is the source of truth**; the
client holds an optimistic copy. One request = "append this message and continue", not "here is
the world".

```
client:  sendMessage(text) --POST {chatId, message}--> server
server:  load history(chatId) -> + message -> save(user msg) -> model(history) --stream--> client
                                                             \-> onEnd: save(assistant msg)
```

## Architecture

Three choices, each with its trade-off:

| Choice | Options | Trade-off |
|---|---|---|
| Owner | client array / **server DB** | server = trust, durability, limits; costs a DB read per turn |
| Shape stored | model messages / **UI parts** (ai-chatbot) | UI parts keep tool UIs, data parts and provider metadata (e.g. Gemini thought signatures) for free; but the schema is coupled to an SDK type and needs migrations (`Message_v2`) |
| Write timing | user msg before model; assistant msg **only on finish** / incrementally / on abort too | finish-only is simplest and **loses the answer on Stop/crash** (teardown 02, F5) |

Also: **transient vs persisted stream parts**. Stream what the UI needs (waiting status,
progress); persist what the conversation needs (text, tool calls and results).

## Example

Teardown 02 (`vercel/ai-chatbot`): the client sends only the new message. History comes from
`Message_v2` and is converted with `convertToModelMessages`. The user message is saved before
the model call and the assistant message in `onEnd`. A weather turn stored 5,661 bytes of parts,
77% of it raw tool output, which is then replayed to the model on every later turn.

## Implementation

Minimum production shape:
1. `POST {chatId, message}`; validate it; check ownership **before** any LLM work.
2. Load history; **bound it** (window, summary, or prune old tool outputs) before the model call.
3. Save the user message; generate; save the assistant message on finish **and on abort/error**
   (partial, flagged).
4. Store per-message usage (tokens, cost, model) next to the message.
5. `timestamptz` for every time column. Rate-limit counts depend on it.

## Trade-offs

- Server-owned history adds a DB round trip and a write per turn. That's negligible next to
  LLM latency (ms vs s).
- Replaying full history makes each turn's input grow linearly, so a chat's *total* input cost
  grows roughly with the square of its turn count (exp-004: everything is re-sent every step). Bounding it trades recall for cost.
- Storing UI shape is faster to build; storing model shape is easier to migrate between SDKs and
  providers.

## Production considerations

- Stop must cancel downstream work (pass the abort signal into nested generations) or at least
  persist what was paid for.
- Resumable streams (publish the SSE to Redis, re-attach on reload) are only worth it if the
  publish and resume paths are both tested. Teardown 02 found both broken.
- Rate limits must be atomic (`INCR` / single SQL statement), not "count, then insert".
- Guest users are real rows: plan cleanup.

## Interview questions

- Why should the server, not the client, own chat history? What attack does it prevent?
- What happens to a streaming answer when the user presses Stop? What should happen?
- How do you keep a 50-turn chat's input cost under control?
- What's the trade-off between storing UI messages and model messages?

## Project application

- **DocPilot RN** (Phase 2): server-owned chats; citations must persist with the message parts.
- **Review Radar** (Phase 3-4): agent runs are long, so persist each step, not only on finish
  (durable execution).
- `packages/llm-kit`: add usage-per-message to whatever persistence helper we build.

## References

- `teardowns/02-ai-chatbot/NOTES.md` (F1-F6, F9), exp-022.
- `teardowns/01-next-fastapi/NOTES.md`: client-owned history, and FIX-8 (provider metadata).
- AI SDK docs, "Chatbot message persistence" and "resumable streams": re-verify at use.
