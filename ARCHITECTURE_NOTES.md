# Architecture Notes

Reference architectures we build toward, in text so they stay diff-able. Each project's `docs/architecture.md` is a concrete instance of one of these. Detailed patterns land in `notes/architecture/` as they are built.

## The full-stack AI reference stack

```
React / Next.js (web)   React Native (mobile)   CLI / GitHub Action
            |                    |                     |
            +--------- HTTPS / SSE / WebSocket --------+
                               |
                    FastAPI (Python) API layer
              auth, tenancy, validation, rate limits, streaming
                               |
                 AI orchestration layer (our code + llm-kit)
       prompts (versioned) | structured outputs | tool loop | routing | budgets
          |                     |                    |
   LLM providers        Retrieval (pgvector,      Tools / external APIs
 (primary, fallback,     full-text, reranker)     (GitHub, stores, MCP)
  local via Ollama)              |
                               Postgres (state, tenants, jobs, traces)  Redis (cache, queue)
                               Object storage (documents)   Observability (traces, costs)
                               Workers / scheduler (background agents, ingestion)
```

Principles: Pydantic at every boundary; every LLM call through one thin layer that logs model, tokens, latency, cost, prompt version; providers swappable by config; state in Postgres, not in process memory; long work in workers, not request handlers; evals runnable with one command.

## Pattern 1: Structured generation service (Phase 1, Changelog Forge)

```
input -> normalise to models -> token-aware chunking
      -> MAP: cheap model, structured output per chunk (parallel, bounded)
      -> REDUCE: capable model merges + writes prose (structured)
      -> render -> output
cost log per stage; golden-set evals on the final structure
```

Decisions to record: chunk size in tokens, routing rule, retry/timeout policy, schema strictness, how hallucinated references are caught (verify IDs against source).

## Pattern 2: RAG service (Phase 2, DocPilot RN)

```
INGEST: source -> parse -> structure-aware chunk (+metadata) -> embed -> upsert (pgvector + tsvector) [idempotent by content hash]
QUERY : question (+filters) -> optional rewrite -> hybrid retrieve (vector k=30, bm25 k=30) -> RRF -> rerank -> top 5-8
      -> assemble context with citation IDs -> generate (grounded, refuse if none) -> verify citations -> stream
EVAL  : golden Q/A -> recall@k, MRR (retrieval) ; faithfulness, relevance, citation correctness (generation) ; cost/latency
```

Decisions: embedding model (local vs API, dims), chunking, index type, k values, reranker, refusal policy, citation format, cache keys.

## Pattern 3: Agent with human-in-the-loop (Phase 3, Review Radar)

```
trigger (schedule / event) -> load task state -> LOOP { model(context + tools) -> tool call? -> execute (read tools directly; write tools => create PROPOSAL, pause) -> append observation } until done | step/cost limit
PROPOSAL -> approval API/UI -> approved => executor runs the write tool, records result -> agent resumes or closes
memory: facts + embeddings in Postgres, retrieved by tool; trajectory: JSONL per run for evals and debugging
```

Decisions: tool schemas and descriptions, read/write split, budgets, pause/resume persistence, what memory stores, dedupe strategy, prompt-injection handling of tool outputs (treat as data, delimit, never merge into system prompt).

## Pattern 4: Production hardening (Phase 4)

Add: auth (hosted provider or JWT) -> tenant_id on every row and every query; queue + workers with idempotency keys; exact and semantic cache; provider fallback + circuit breaker; per-tenant budgets and alerts; tracing of every LLM call; prompt/model versions pinned and evaluated in CI on a schedule; injection red-team suite; Docker multi-stage; GitHub Actions lint -> test -> build -> deploy; health checks; runbook.

## Data-flow questions to answer in every design review

1. Where does untrusted text enter, and where could it reach a prompt?
2. What is the maximum context this path can build, and what caps it?
3. What is the cost of the worst-case request, and who pays for a runaway loop?
4. What happens when the provider returns 429, 500, or garbage JSON?
5. What state survives a crash mid-request, and how does a retry avoid duplicate side effects?
6. How would we know this path regressed after a prompt or model change?
