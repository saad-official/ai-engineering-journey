# AI Engineering Roadmap

> From Senior Frontend/Full-Stack Engineer to Full-Stack AI Engineer, through building.
> Owner: Saad (github.com/saad-official). Started: September 2026. Living document; revise at each phase exit.

## How to read this

- **Phases are sequential, projects are cumulative.** Each phase ends with a major project that reuses what the previous one produced. Nothing is a throwaway tutorial.
- **Time estimates assume 8-12 focused hours per week** alongside a full-time job. Roughly nine months end to end. If a phase takes longer, that is fine; skipping the exit criteria is not.
- **Courses supply theory, this workspace supplies skill.** The mapping of owned courses to phases lives in `LEARNING_PLAN.md`.
- **Every technology choice and its cost is recorded in `TECHNOLOGY_STACK.md`.** This file refers to "the primary provider", "the vector store", etc. so it does not go stale when a vendor changes pricing.
- **Fundamental vs fast-changing** is marked throughout: `[F]` = durable concept, learn deeply. `[T]` = tool that may churn, learn enough to use and to evaluate replacements.

## The learning loop (every concept, every phase)

```
Learn concept (course / mentor)
  -> Small experiment (labs/, experiments/)
  -> Understand the architecture (notes/concepts/*.md, ARCHITECTURE_NOTES.md)
  -> Build feature -> Build project (projects/)
  -> Test + Eval -> Deploy -> Document (README, architecture, decisions, lessons)
  -> Review with the team agents (reviewer, qa, architect)
  -> Improve -> Add to portfolio -> Repeat
```

## Phase map

| Phase | Name | Weeks (approx.) | Major project | Capability proved |
|---|---|---|---|---|
| 0 | Setup and baseline | 1 | Workspace + first LLM call | Environment, provider access, repo hygiene |
| 1 | Python for AI + LLM API fundamentals | 2-5 | **Changelog Forge**: AI release-notes generator (CLI + API + GitHub Action) | LLM integration, structured outputs, context management, cost control |
| 2 | Embeddings, retrieval, RAG | 6-11 | **DocPilot RN**: version-aware docs assistant for React Native / Expo | Embeddings, vector search, hybrid retrieval, reranking, RAG evaluation, streaming UI |
| 3 | Agents and tool use | 12-17 | **Review Radar**: app-store review intelligence agent | Agent loops, tool calling, planning, memory, human-in-the-loop, scheduled agents, MCP |
| 4 | Production AI engineering | 18-23 | **Review Radar -> multi-tenant SaaS** | Auth, Postgres, queues, caching, observability, evals in CI, security, deployment |
| 5 | Entrepreneurial AI SaaS | 24-35 | One product chosen with the product-strategist agent | Idea -> architecture -> AI -> deploy -> users; full-stack AI + product thinking |
| 6 | Career packaging (parallel from week ~20) | 20-36 | Resume, portfolio, interview prep | Employability |

---

## Phase 0: Setup and baseline (week 1)

**Goal.** A clean, cost-free, company-separated environment where every later phase can start in minutes.

**Learning objectives**
- Understand the modern Python project toolchain well enough to explain it (`uv`, `pyproject.toml`, lockfiles, `ruff`, `pytest`) and how it maps to npm/pnpm + eslint + jest. `[T]` tools, `[F]` concepts.
- Make one LLM API call through an OpenAI-compatible client against the primary free provider, and read the response object (tokens, finish reason, model) with understanding.
- Run one small local model and one local embedding model; know what "quantized GGUF" means at a high level.

**Technologies**: `uv`, Python 3.12 pinned per project (broadest wheel support; the system Python 3.14 stays untouched), `ruff`, `pytest`, `httpx`, `pydantic`, `pydantic-settings`, Gemini API key (primary) + Groq key (secondary) + OpenRouter key (model zoo), Ollama installed on G: with the model set from `TECHNOLOGY_STACK.md`, Docker Desktop (already installed), `gh` CLI authenticated as saad-official (currently logged in as a different account; switch first).

**Hands-on exercises (labs/00-setup, labs/01-hello-llm)**
1. Install `uv`; create `labs/01-hello-llm` with a pinned interpreter, a `.env.example`, and a `pyproject.toml`.
2. Send the same prompt to (a) the primary cloud provider and (b) a local model via Ollama's OpenAI-compatible endpoint by changing only `base_url` and `model`. Log tokens used and elapsed time for each.
3. Compute the cost of the cloud call from the provider's price sheet by hand. Write it in `EXPERIMENTS.md`.

**Deliverables**
- This repo initialised as its own git repository (nested inside the `G:\` repo is fine), pushed to `github.com/saad-official/ai-engineering-journey`, with personal git identity configured locally.
- `TECHNOLOGY_STACK.md` decisions confirmed against live pricing pages (already drafted; re-verify keys and limits when you sign up).
- API keys for the primary and secondary provider stored in `.env` only.

**Exit criteria / what you can explain**
- Why `uv` + lockfile (reproducibility, speed) and why one `.venv` per project.
- What a token is, roughly how many tokens a page of text is, and why cost and context are both measured in tokens.
- Why the same code can talk to three providers (OpenAI-compatible API shape) and what that abstraction hides (tool-calling and structured-output differences).

---

## Phase 1: Python for AI engineers + LLM API fundamentals (weeks 2-5)

**Goal.** Become comfortable writing production-shaped Python and treating an LLM as a well-understood, cost-controlled, testable dependency rather than a magic box.

**Learning objectives**
- Python `[F]`: modules and packaging, type hints and generics, dataclasses vs Pydantic models, `async`/`await` with `httpx` and `asyncio.gather`, context managers, generators (for streaming), exceptions and retries, logging, `pytest` fixtures and parametrisation, mocking HTTP with `respx`.
- LLM fundamentals `[F]`: tokens, tokenizers, context windows, system/developer/user roles, temperature and top-p, max tokens, stop sequences, streaming (SSE), structured outputs (JSON schema / Pydantic), function and tool calling, model selection (small vs frontier), hallucination and its mitigations, prompt versioning as code.
- Engineering `[F]`: idempotency, retries with exponential backoff on 429/5xx, timeouts, rate limiting client-side, token counting before sending, chunk-and-merge (map-reduce) for inputs bigger than the context window, cost per request logging.
- FastAPI `[T]` basics: routers, Pydantic request/response models, dependency injection, background tasks, streaming responses, OpenAPI docs, settings management.

**Concepts to write up in `notes/concepts/`**: tokens-and-context-windows, prompting-and-message-roles, generation-parameters, structured-outputs, tool-calling, streaming, hallucination-and-grounding, provider-abstraction, cost-and-latency-basics, prompt-versioning.

**Hands-on exercises (labs/02 .. labs/09)**
1. `tokens`: count tokens with a tokenizer library for five texts; compare against the provider's reported usage; explain the differences.
2. `params`: same prompt at temperature 0, 0.7, 1.2 for 5 runs each; observe variance; write two sentences on when you would use each.
3. `structured`: extract a Pydantic model (`Invoice`, `JobPosting`, whatever) from messy text using native structured outputs; then break it with adversarial input and add validation.
4. `tools`: implement a two-tool loop by hand (`get_weather`, `calculate`) with no framework: model -> tool call -> execute -> return result -> final answer. Log the full message array at each step.
5. `stream`: stream a completion to the terminal, then to a FastAPI endpoint via SSE, then consume it from a tiny React page with `fetch` + `ReadableStream`. This is where your frontend skill meets AI.
6. `retry`: wrap the client with timeouts, retries, and a token budget guard; unit test it with `respx` fixtures simulating 429s.
7. `map-reduce`: summarise a 60-page public document that does not fit one context: chunk, summarise each, merge, compare against a single-shot summary on a smaller doc.
8. `providers`: run exercises 3 and 4 against the primary provider, the secondary provider, and a local model; record where tool calling or JSON mode differs or fails. This experience is the reason we do not marry one vendor.

**Mini projects**
- `llm-kit` (inside this repo, `packages/llm-kit`): a *thin* internal library, about 300 lines, exposing `complete()`, `complete_structured(model: type[BaseModel])`, `stream()`, and `call_tools()` over an OpenAI-compatible client, with retries, token/cost accounting, and a pluggable provider config. Not a framework. Every later project imports it, and you understand every line.
- `prompt-lab` CLI: run a prompt file against N models and a small golden set; print a comparison table. Seeds your eval habit early.

**Major project: Changelog Forge (Level 1)**
AI release-notes and changelog generator. Input: a git range or GitHub compare URL. Output: structured release notes for two audiences (end users, developers), categorised (features, fixes, breaking changes, internal), with links back to commits/PRs. Interfaces: CLI, FastAPI endpoint, GitHub Action that comments on a release PR.
- Why it is not a toy: real maintainers need it, diffs routinely exceed the context window (forces chunking and map-reduce), quality is measurable (golden set of real repos with hand-written notes), and cost per run matters (a 400-commit range must not cost dollars).
- AI components: structured outputs, prompt templates versioned in the repo, chunking strategy, model routing (cheap model for classification, better model for prose), eval harness with code-based scorers (every breaking change mentioned? every PR linked?).
- Full spec and the 12-question evaluation are in `PROJECTS.md`.

**Expected skills after Phase 1**
Professional Python for services; confident use of any OpenAI-compatible LLM API; structured outputs and tool calling by hand; streaming end to end to a React client; cost and token discipline; first eval harness; first FastAPI service; first GitHub Action.

**Recommended documentation**: `notes/concepts/*` (10 notes above), `projects/changelog-forge/README.md`, `docs/architecture.md`, `docs/decisions/0001-model-routing.md`, `docs/evals.md`, EXPERIMENTS.md rows for labs 1-8.

**GitHub deliverables**: `ai-engineering-journey` repo with labs and notes; `changelog-forge` repo (public, README with GIF, Action published), a GitHub release generated by itself.

**Interview: you should be able to explain**
- What a token is and why context windows and pricing are token-based. How you estimate cost before a call.
- The difference between JSON mode, JSON schema / structured outputs, and tool calling, and when to use each.
- How the tool-calling loop works, message by message, with no framework.
- Why temperature 0 does not guarantee determinism. What you do about non-determinism in tests.
- How you handled inputs larger than the context window and how you evaluated that the summary did not lose facts.
- How you would swap providers and what would break.

---

## Phase 2: Embeddings, retrieval, and RAG (weeks 6-11)

**Goal.** Build retrieval systems that are measurably better than "stuff the prompt", and know exactly why and when RAG is the right tool.

**Learning objectives**
- Embeddings `[F]`: what a vector represents, dimensionality, cosine vs dot product, embedding models (local vs API), why the same model must embed queries and documents, normalisation, cost of embedding at scale.
- Chunking `[F]`: fixed-size vs recursive vs structure-aware (Markdown headings, code blocks), overlap, chunk metadata (source, version, section, URL), parent-child / small-to-big retrieval.
- Vector storage `[F]/[T]`: pgvector on Postgres (primary), HNSW vs IVFFlat at a conceptual level, metadata filtering, when a dedicated vector DB is worth it.
- Retrieval quality `[F]`: top-k, similarity thresholds, hybrid search (BM25/full-text + vector, reciprocal rank fusion), reranking with a cross-encoder, query rewriting, HyDE, multi-query, when each helps.
- RAG pipeline `[F]`: ingest -> parse -> chunk -> embed -> index; query -> retrieve -> (rerank) -> assemble context with citations -> generate -> cite. Grounding instructions, refusal when nothing relevant, citation formats the UI can render.
- Evaluation `[F]`: retrieval metrics (recall@k, MRR), answer metrics (faithfulness, relevance, citation correctness), building a golden Q/A set, LLM-as-judge with rubric and its pitfalls, regression testing when chunking or models change.
- Document processing `[T]`: Markdown, HTML, PDF, code files; a parsing library evaluated in `experiments/`.
- Frontend `[F]`: streaming answers with citations into a Next.js UI; optimistic UI for ingestion status.

**Concepts to write up**: embeddings, similarity-search, chunking-strategies, vector-databases-and-pgvector, hybrid-search-and-rrf, reranking, rag-pipeline, rag-evaluation, query-transformations, citations-and-grounding, when-not-to-use-rag.

**Hands-on exercises (labs/10 .. labs/17)**
1. `embed-explore`: embed 50 sentences locally; compute a similarity matrix; find the surprising neighbours; plot with a 2-D projection. Build intuition.
2. `chunk-compare`: chunk one long Markdown doc four ways; for 10 questions, measure which chunking retrieves the right passage. Record results in `EXPERIMENTS.md`.
3. `pgvector-basics`: Docker Postgres with pgvector; insert embeddings; query with cosine distance and a metadata filter; add an HNSW index and compare latency at 10k rows.
4. `hybrid`: add Postgres full-text search; fuse with vector results using reciprocal rank fusion; find three queries where hybrid wins and one where it loses.
5. `rerank`: add a local cross-encoder reranker; measure recall@5 before and after on your golden set.
6. `rag-minimal`: end-to-end RAG in about 150 lines with citations; then deliberately ask an out-of-corpus question and make it refuse gracefully.
7. `eval-rag`: build the golden set (30 questions) and an eval script printing recall@k, faithfulness (judge), and cost per question. Run it after every pipeline change.
8. `rag-vs-long-context`: same questions answered by RAG vs by putting the whole corpus in a long-context model. Compare quality, latency, and cost. Write the trade-off note.

**Mini projects**
- `ingest-cli`: parse a folder of Markdown/PDF/HTML into chunks with metadata; idempotent re-ingestion (content hashing) so re-runs do not duplicate.
- `rag-eval` module added to `llm-kit` or its own small package; reused in Phases 3-5.

**Major project: DocPilot RN (Level 2)**
A version-aware documentation assistant for React Native and Expo (and later any versioned SDK). Ask "how do I do X in Expo SDK 5x" and get an answer grounded in the docs for *that* version, with citations, code blocks preserved, and a warning when the API changed between versions.
- Why it is not a toy: version drift is a real, daily pain for RN developers; you can judge answer quality yourself; it needs metadata filtering (version), structure-aware chunking (code blocks must not be split), hybrid search (exact API names), and reranking. Public docs are freely available.
- Architecture: ingestion worker (docs -> chunks -> pgvector), FastAPI query service with streaming + citations, Next.js frontend (chat with version selector, citation side panel), eval harness with a golden set of version-specific questions.
- Differentiator: version-diff answers ("this changed in SDK 51: ...") produced by retrieving the same section across two versions.
- Full spec in `PROJECTS.md`.

**Expected skills after Phase 2**
Design and defend a RAG architecture; choose chunking/retrieval strategies from measurements rather than folklore; run Postgres + pgvector locally and in the cloud; build and use a retrieval eval set; stream grounded answers with citations into a React UI.

**Recommended documentation**: the 11 concept notes; `ARCHITECTURE_NOTES.md` RAG reference architecture; `projects/docpilot-rn/docs/{architecture,evals,ingestion}.md`; decision records for chunking strategy and vector store.

**GitHub deliverables**: `docpilot-rn` repo (backend + frontend, deployed demo URL, eval results table in README, screenshots), `ai-engineering-journey` updated with labs 10-17 and experiment findings.

**Interview: you should be able to explain**
- Why RAG instead of fine-tuning or long context; when long context wins.
- How you chose chunk size and overlap, with numbers.
- Hybrid search: what BM25 catches that embeddings miss, and how you fused the rankings.
- What a reranker is, why it is a cross-encoder, and why you do not rerank 10,000 documents.
- How you evaluated retrieval and generation separately; what your golden set looks like; what "faithfulness" means.
- How you prevented prompt injection from a retrieved document and how citations are verified.
- pgvector vs a dedicated vector database: the trade-off and where you would switch.

---

## Phase 3: Agents and tool use (weeks 12-17)

**Goal.** Build agents that do real multi-step work reliably, first with no framework so the mechanics are yours, then evaluate frameworks with judgement.

**Learning objectives**
- Agent loop `[F]`: observe -> think -> act (tool) -> observe, termination conditions, step limits, cost limits, tool schemas as the contract, error feedback to the model, parallel tool calls.
- Planning and decomposition `[F]`: plan-then-execute vs ReAct-style interleaving, subtask routing to cheaper models, when a fixed workflow beats an agent (most of the time).
- State and memory `[F]`: conversation state vs task state vs long-term memory; summarisation of history; memory stored in Postgres and retrieved via embeddings; what to persist and why.
- Reliability `[F]`: idempotent tools, dry-run mode, human-in-the-loop approval gates, retries at the tool level vs the loop level, guardrails on outputs, sandboxing side effects, observability of trajectories.
- Orchestration `[F]/[T]`: workflows as graphs (nodes, edges, checkpoints), durable execution and resumability, background workers and scheduled runs; then LangGraph and Pydantic AI evaluated hands-on against your own loop.
- Model Context Protocol `[T]` (with `[F]` idea: standardised tool servers): build a small MCP server exposing your project's tools; connect it to a client.
- Multi-agent `[F]`: when splitting into specialised agents helps (separation of context, permissions) and when it just adds cost.
- Agent evaluation `[F]`: trajectory checks (did it call the right tool with the right args), outcome checks, cost/step budgets, replaying recorded tool results for deterministic tests.

**Concepts to write up**: agent-loop, tool-design, planning-vs-workflows, agent-memory, human-in-the-loop, durable-execution-and-checkpoints, mcp, multi-agent-patterns, agent-evaluation, agent-security.

**Hands-on exercises (labs/18 .. labs/25)**
1. `loop-from-scratch`: a 100-line agent with 3 tools, step and cost limits, and full trajectory logging to JSONL.
2. `tool-design`: rewrite a bad tool (vague description, giant blob output) into a good one; measure the model's success rate on 10 tasks before and after.
3. `plan-execute`: same tasks solved with plan-then-execute vs ReAct; compare steps, cost, and success.
4. `memory`: give the agent long-term memory in Postgres (facts + embeddings); verify it recalls across sessions; decide what NOT to store.
5. `hitl`: add an approval gate before any write action; persist the paused state; resume after approval via an API call.
6. `background`: run the agent as a background job with a queue and a worker; add a scheduled trigger.
7. `langgraph-vs-mine` (experiments/): port lab 5 to LangGraph and to Pydantic AI; write a comparison of what each gave you and what it cost in complexity.
8. `mcp-server`: expose two project tools via an MCP server; call them from an MCP client (Claude Code or a small Python client).

**Mini projects**
- `agent-kit` additions to `llm-kit`: tool registry from Python functions with Pydantic schemas, trajectory logger, budget guard.
- `github-triage-bot`: a scheduled agent that labels and summarises new issues on one of your public repos with a dry-run mode. Small, real, and safe.

**Major project: Review Radar (Level 3)**
An agent that monitors public app-store reviews for a mobile app (App Store + Google Play), clusters them into themes with embeddings, extracts structured signals (bugs, feature requests, sentiment, device/OS, app version), drafts replies, and proposes GitHub issues. All write actions go through a human approval queue. Runs on a schedule.
- Why it is not a toy: indie and small-team mobile developers really do drown in reviews; you know the domain; it exercises tools with real external APIs, embeddings (from Phase 2), structured outputs (Phase 1), scheduled execution, memory (what was already triaged), and human-in-the-loop.
- Architecture: scheduler -> fetch tools -> dedupe against Postgres -> cluster (embeddings) -> per-cluster analysis (cheap model) -> draft replies / issues -> approval queue (FastAPI + Next.js dashboard) -> execute approved actions via tools. Trajectories logged and evaluable.
- Full spec in `PROJECTS.md`.

**Expected skills after Phase 3**
Write an agent loop from scratch and explain every design decision; design tools models use well; add memory, planning, approval gates, and background execution; evaluate agents by trajectory and outcome; use LangGraph or Pydantic AI with informed judgement; build and consume an MCP server.

**Recommended documentation**: 10 concept notes; `ARCHITECTURE_NOTES.md` agent reference architecture; `experiments/langgraph-vs-mine/README.md`; `projects/review-radar/docs/{architecture,tools,evals,safety}.md`.

**GitHub deliverables**: `review-radar` repo (runs on a schedule against a public app you choose, dashboard deployed, trajectory examples in README); MCP server published as a small package or folder.

**Interview: you should be able to explain**
- The agent loop with no framework, including termination and budget controls.
- What makes a tool description good; how you measured it.
- When you would NOT build an agent and use a fixed workflow instead.
- How memory works in your agent, what is stored, how it is retrieved, and its failure modes.
- How human-in-the-loop is implemented technically (paused state, persistence, resume).
- How you tested an agent deterministically; how you evaluate trajectories.
- What MCP standardises and why that matters for tool reuse.
- Prompt injection through tool results and how the agent is protected.

---

## Phase 4: Production AI engineering (weeks 18-23)

**Goal.** Turn Review Radar into something real users could sign up for, and learn the production concerns that separate demos from products.

**Learning objectives**
- Backend `[F]`: authentication (JWT or a hosted auth provider) and authorisation (per-tenant data isolation), Postgres schema design with migrations (Alembic), row-level tenant scoping, background workers and queues, idempotency keys, rate limiting per user, pagination.
- Reliability and cost `[F]`: response caching (exact and semantic), prompt caching where the provider supports it, model routing, fallbacks across providers, circuit breakers, budgets and alerts per tenant, batch APIs for non-urgent work.
- Observability `[F]/[T]`: structured logs with request IDs, tracing every LLM call (prompt, tokens, latency, cost, model, version) into an observability tool, dashboards, error alerting.
- Evaluation in the lifecycle `[F]`: eval suite in CI (scheduled), prompt and model version pinning, canary comparisons before switching models, regression datasets grown from production failures.
- Security and privacy `[F]`: prompt injection defence in depth, output validation, PII minimisation and redaction, secrets management, abuse prevention (quotas, auth, allow-lists for tools), data retention policy, supply-chain basics.
- Deployment `[F]/[T]`: Docker multi-stage images, CI/CD with GitHub Actions, environment separation (dev/staging/prod), cheapest cloud target from `TECHNOLOGY_STACK.md`, managed Postgres, health checks, zero-downtime-ish deploys, rollback, cost monitoring.

**Concepts to write up**: multi-tenancy-and-authz, caching-for-llm-apps, model-routing-and-fallbacks, llm-observability, prompt-and-model-versioning, evals-in-ci, prompt-injection-defence, pii-and-privacy, rate-limits-and-budgets, deployment-architecture.

**Hands-on exercises (labs/26 .. labs/31)**
1. `auth`: add sign-up/login and tenant scoping to a FastAPI service; write a test that proves tenant A cannot read tenant B's rows.
2. `queue`: move a slow LLM job to a worker; return a job ID; poll or push status to the UI.
3. `cache`: add exact-match and semantic caching; measure hit rate and cost savings on the eval set.
4. `trace`: instrument every LLM call; view a trace end to end; find the slowest step and the most expensive prompt.
5. `fallback`: kill the primary provider (bad key) and prove the fallback works with an alert emitted.
6. `redteam`: write 20 injection attempts against your own system (via reviews, docs, tool outputs); record which succeed; fix; re-run.

**Major project: Review Radar SaaS (Level 4)**
Multi-tenant, authenticated, deployed, observable, evaluated in CI, with cost controls per tenant and a real onboarding flow (connect an app, see first insights within minutes). Billing-ready structure (plans and quotas) without necessarily charging.

**Expected skills after Phase 4**
Ship and operate an AI service: auth, data isolation, queues, caching, observability, evals in CI, security hardening, cost monitoring, Docker + CI/CD + cloud deployment, incident basics.

**Recommended documentation**: 10 concept notes; `ARCHITECTURE_NOTES.md` production reference architecture; `projects/review-radar/docs/{deployment,security,observability,runbook,costs}.md`.

**GitHub deliverables**: production deployment URL, status/health endpoint, CI badges, eval results published per release, an honest `costs.md` with real numbers.

**Interview: you should be able to explain**
- Your production architecture end to end, including where state lives and what happens when each component fails.
- How you isolate tenants and prove it.
- Cost controls: caching, routing, budgets, batch; with measured savings.
- Your observability setup and a real debugging story from it.
- How prompts and models are versioned and how a model change is validated before rollout.
- Your threat model for prompt injection and data leakage, and the defences you implemented.
- What you would change at 100x users.

---

## Phase 5: Entrepreneurial AI SaaS (weeks 24-35)

**Goal.** Build one product with real users that demonstrates AI Engineering + full-stack engineering + product thinking, from idea to production.

**Process**
1. Idea sprint with the `product-strategist` agent: 5-8 candidates, each scored with the 12 questions in `PROJECTS.md` and unit economics. Domains you own personally (mobile dev tooling, RN/Expo ecosystem, indie publishing, developer productivity). Never your employer's domain.
2. Riskiest-assumption test: a landing page, 5 conversations with target users, or a manual concierge version. One week maximum.
3. Architecture with the `architect` agent; reuse `llm-kit`, the RAG module, the agent-kit, and the Phase 4 production template.
4. Build in vertical slices (something a user can touch each week). Next.js + FastAPI + workers + Postgres/pgvector; React Native companion only if the product needs it.
5. Launch: deployed, documented, telemetry on, small group of real users, feedback loop.
6. Post-launch: cost per active user, eval results, roadmap.

**Candidate seeds (to be scored, not decided yet)**
- Review Radar as the product itself (already built; the question is distribution).
- Localisation QA agent for mobile apps: checks translated strings for meaning drift, placeholder breakage, length overflow, and cultural issues; screenshot-based multimodal review.
- Crash and ANR triage assistant: ingest crash logs and symbolicated traces, cluster, explain likely root causes with code context, draft the fix PR under approval.
- Store-listing and release-marketing copilot for indie apps, grounded in the actual changelog (reuses Changelog Forge) and reviews (reuses Review Radar).
- Version-migration assistant for RN/Expo upgrades, grounded in DocPilot RN's versioned corpus, proposing codemods under approval.

**Expected skills after Phase 5**
End-to-end ownership of an AI product; product discovery; unit economics of LLM features; shipping to real users; the ability to tell the whole story in an interview.

**GitHub deliverables**: product repo with the full documentation set, live URL, demo video, `docs/business.md` (problem, users, economics, what you learned).

---

## Phase 6: Career packaging (parallel from about week 20)

Detailed in `CAREER_PLAN.md`. In short: rewrite the resume around outcomes and AI-engineering capabilities proven by the projects; portfolio site with the four projects and their architecture diagrams; GitHub profile README; project write-ups; system-design practice on LLM apps; mock interviews with the `mentor` agent; target roles chosen from actual strengths (likely Full-Stack AI Engineer / AI Application Engineer / Applied AI Engineer / Forward Deployed Engineer).

---

## Cross-cutting threads (revisit every phase)

- **Cost discipline**: every project logs tokens and cost per request from day one; `costs.md` in every project.
- **Evaluation**: every project has a golden set and one command to run evals, starting with Changelog Forge.
- **Security**: prompt injection thinking starts in Phase 1 (structured extraction of hostile text) and deepens each phase.
- **Frontend advantage**: every project has a polished UI where it matters. This is a differentiator most AI engineers lack.
- **Documentation**: every concept becomes a note; every decision a record; every project a full README set.
- **Python growth**: Phase 1 syntax and structure; Phase 2 data processing and Postgres; Phase 3 async workers and state machines; Phase 4 production patterns; Phase 5 the whole stack.

## Framework policy

Build the concept by hand first, then evaluate the framework in `experiments/` against your own implementation, then adopt only if it pays for its complexity. Current stance (details, versions, and dates in `TECHNOLOGY_STACK.md`): no framework in Phases 1-2 beyond thin `llm-kit`; Vercel AI SDK 7 on the frontend from Phase 2 because streaming UI maps directly to your React strength; in Phase 3 Pydantic AI first (most readable, typed, provider-agnostic) then LangGraph 1.x (most named in job postings; durable state, interrupts, human-in-the-loop), both compared against your own loop; MCP server and client in Phase 3 with pinned SDK versions; LlamaIndex tried once in Phase 2 to learn its vocabulary, not adopted as the app framework; Docling and pymupdf4llm for document parsing; Langfuse for tracing from Phase 2; DeepEval or RAGAS as the CI eval gate from Phase 4. Skip unless a job requires them: CrewAI, Google ADK, Microsoft Agent Framework, Haystack, A2A.

## Revision log

| Date | Change |
|---|---|
| 2026-09-05 | Initial roadmap created. |
