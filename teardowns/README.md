# Teardowns

Reverse-engineering real open-source AI apps. Labs build a concept by hand. A teardown then
reads how a maintained product built the same thing, runs it, breaks it, and diffs it against
our lab. The rule from CLAUDE.md still holds: **tear down an app only after building its
concept by hand**. Otherwise it's just complicated code.

## Method (every teardown)

1. **Predict first.** Before opening the code, write how you would build it (top of `NOTES.md`).
2. **Trace one request** from UI to response. List every file it passes through. Ignore
   everything off that path (auth, settings, UI chrome).
3. **Run it** against our free providers. Keep their source **unmodified**: swap clients and
   models from a harness at the seams (see `01-next-fastapi/run_original.py`), so what we
   observe is what they wrote.
4. **Capture the wire.** Save raw request/response bytes and raw provider chunks into
   `captures/`. Read the bytes before reading the translator.
5. **Break one thing** on purpose and record what fails and how loudly.
6. **Diff against our lab**: what they did better (steal it), and what we did better.
7. **Write `NOTES.md`**: flow diagram, findings with captures, things to steal, and 3–4
   explain-back questions. Add one row to `EXPERIMENTS.md`.

Layout: `teardowns/NN-name/` (our harness, captures, notes; committed) and `teardowns/_src/`
(sparse clones of upstream repos; gitignored, never edited).

## The ladder

Repo status was checked on GitHub on 2026-09-26 by the researcher agent. Re-check activity
before starting a tier.

| # | Repo | Tier / phase | The one flow to trace | Status |
|---|---|---|---|---|
| 01 | [vercel/ai `examples/next-fastapi`](https://github.com/vercel/ai/tree/main/examples/next-fastapi) | 1 · streaming + tools | `useChat` → FastAPI → stream protocol → tool parts | **done**: [`01-next-fastapi/NOTES.md`](01-next-fastapi/NOTES.md) |
| 02 | [vercel/ai-chatbot](https://github.com/vercel/ai-chatbot) | 1 · persistence, resumable streams | `api/chat/route.ts` → `streamText` + tools → Drizzle/Postgres → resumable stream | **done**: [`02-ai-chatbot/NOTES.md`](02-ai-chatbot/NOTES.md) |
| 03 | [Azure-Samples/rag-postgres-openai-python](https://github.com/Azure-Samples/rag-postgres-openai-python) | 2 · RAG | route → query rewriter → `postgres_searcher.py` (hybrid + RRF in SQL) → cited answer | after the Phase 2 RAG labs |
| 04 | [Vane (ex-Perplexica)](https://github.com/ItzCrazyKns/Vane) | 2 · answer engine | classify → research → write with citations (SearxNG) | |
| 05 | [langchain-ai/react-agent](https://github.com/langchain-ai/react-agent) | 3 · framework vs our loop | state → `call_model` → conditional edge → `ToolNode` → loop | can read now, next to Lab 04 |
| 06 | [pydantic-ai examples](https://github.com/pydantic/pydantic-ai/tree/main/examples/pydantic_ai_examples) | 3 · typed agents | `chat_app.py`, `rag.py` (pgvector) | |
| 07 | [SWE-agent/mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent) | 3 · coding agent in ~100 lines | the observation loop | |
| 08 | [modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers) | 3 · MCP | `fetch` (Py) then `filesystem` (TS): register → `call_tool` → stdio | |
| 09 | [langfuse/langfuse](https://github.com/langfuse/langfuse) | 4 · observability | ingestion API → queue → worker → storage | start of Phase 4 |
| 10 | [onyx-dot-app/onyx](https://github.com/onyx-dot-app/onyx) | 4 · enterprise RAG | one question → chat → search tool → index, with permission filtering | start of Phase 4; huge, trace one flow only |
| alt | [miurla/morphic](https://github.com/miurla/morphic) | 2→4 bridge (TS) | AI SDK answer engine with rate limits, usage budgets, evals | optional |

**Rejected (as reading material):** Open WebUI, Dify, LibreChat, AnythingLLM and RAGFlow are
too large and the AI flow is buried in plumbing. Use them as products. aider is slowing down,
and mini-swe-agent teaches the same loop in about 1% of the code. chat-langchain's interesting
parts are now behind a managed platform. open_deep_research is archived.

## What each teardown has taught so far

- **01:** a wire protocol between two languages is an API with no compiler. The example's
  frontend was upgraded and its Python backend wasn't, and nothing turned red. Also,
  "OpenAI-compatible" breaks on tool-call chunking, `finish_reason`, usage placement and
  Gemini's `thought_signature`. exp-021.
- **02:** production chat means the server owns the conversation (the client sends one message)
  and stores UI parts verbatim. The failure surface is Stop and reload: work continues after
  Stop, the answer is lost, and resume is half-removed. Oversized tool output is billed again on
  every later turn. exp-022.

Running a full app (02 onward): install on a drive with room (node_modules ~900 MB), use PGlite
behind `pglite-socket` instead of Docker Postgres, swap only the provider file, and record the
diff (`harness/providers.patch`).
