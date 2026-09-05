# Technology Stack and Decisions

Every provider, service, and framework decision, with the cost and the reasoning. Prices and free tiers were verified against official pages on **2026-09-05** by the researcher agent; items marked UNVERIFIED could only be confirmed from secondary sources. Re-verify anything here before relying on it in a new month; vendors changed several tiers in 2026 alone.

Decision rule: free + good enough, then cheapest practical, then paid only when justified (why, free alternative, expected cost, temporary or recurring, replaceable later).

## Decisions at a glance

| # | Question | Decision | Monthly cost |
|---|---|---|---|
| 1 | Primary LLM provider | Google Gemini API free tier (gemini-2.5-flash-lite / 3.5-flash-lite for work, 3.8-flash when quality matters) | $0 |
| 2 | Secondary / fallback provider | Groq free tier (gpt-oss-20b / 120b, qwen3.8-27b); OpenRouter `:free` as model zoo | $0 (optional one-time $10 to OpenRouter later) |
| 3 | Local models | Ollama on G: with Qwen3.5-4B, Qwen3-1.7B, Qwen3-Embedding-0.6B, nomic-embed-text; optional bge-reranker via llama-server | $0 |
| 4 | Cloud (Phases 1-3) | Render free (FastAPI) + Vercel Hobby (Next.js); no credit card | $0 |
| 4b | Cloud (Phases 4-5) | Google Cloud Run always-free (FastAPI container) + Cloudflare Workers static assets (frontend) | $0 with budget alert; card required |
| 5 | Database | PostgreSQL on Neon free tier (local: Docker `pgvector/pgvector` image) | $0 |
| 6 | Vector database | pgvector in the same Postgres; Qdrant Cloud free cluster only as a comparison experiment | $0 |
| 7 | AI frameworks | None in Phases 1-2 (thin `llm-kit`); Vercel AI SDK 7 on the frontend from Phase 2; Pydantic AI then LangGraph 1.x in Phase 3; MCP in Phase 3; Langfuse for tracing; DeepEval/RAGAS plus own harness for evals | $0 |
| 8 | Deployment stack | uv + Docker multi-stage + GitHub Actions + GHCR; Render early, Cloud Run later; Neon; Upstash Redis; QStash/Inngest for schedules; Cloudflare R2 for files; Langfuse Hobby | $0 |
| 9 | Project structure | This repo = docs + labs + experiments + `packages/llm-kit`; each major project its own repo with a standard layout (below) | – |
| 10 | First project | `labs/01-hello-llm` in week 1, then Changelog Forge (Phase 1 major project) | $0 |

Expected total spend for Phases 0-3: **$0**. First justified spend: a one-time $10 OpenRouter top-up (unlocks 1,000 free requests/day permanently) and, in Phase 3-4, a few dollars on Claude Haiku 4.5 or OpenAI gpt-5-nano to learn the two SDKs that frameworks and job postings target.

---

## 1. LLM providers

### Landscape facts that shaped the decision (Sept 2026)
- GitHub Models was retired on 2026-07-30. Hugging Face free inference credits are $0.10/month. Neither is usable.
- Google stopped publishing free-tier RPM/RPD tables; the live numbers are shown in AI Studio at aistudio.google.com/rate-limit. Gemini "Standard" API keys stop working in September 2026; create a new-style key.
- Together AI removed all serverless embedding and rerank models. SambaNova free is 20 requests/day. Cerebras free is 5 RPM. None can be a primary.
- OpenAI has no free tier. Anthropic gives a small unverified signup credit. Both are paid-only in practice.

### Primary: Google Gemini API (AI Studio)
- **Why.** The only permanent, no-card free tier that covers chat with function calling and JSON-schema structured outputs (1M-token context), a free embedding model (gemini-embedding-2), and a free near-frontier model (gemini-3.8-flash), plus an OpenAI-compatible endpoint (`/v1beta/openai/`) so the same client code works everywhere.
- **Models.** Workhorse: `gemini-3.5-flash-lite` ($0.30/$2.50 per 1M tokens when paid; free tier available). Note: `gemini-2.5-flash-lite` ($0.10/$0.40) still appears in the model list but returns "no longer available to new users" for keys created in Sept 2026, so it is not an option for us. `gemini-flash-lite-latest` is a floating alias; pin explicit versions in projects. Quality tier: `gemini-3.8-flash` ($0.75/$3.75 promo through 2026-12-31). Embeddings: `gemini-embedding-2` (128-3072 dims, $0.20 paid, free tier available).
- **Limits.** Free RPM/RPD are UNVERIFIED from public docs (third-party ballpark: Flash-Lite ~30 RPM, Flash ~10 RPM, Pro 5 RPM / 100 RPD). Read them in AI Studio after creating the key and record them here.
- **Gotchas.** Free-tier prompts are used to improve Google's products: **never send private or company data through the free tier**. Tier 1 (link billing, no minimum spend) removes that and raises limits. Some regions have been excluded from the free tier historically (UNVERIFIED for 2026).
- **SDK.** `google-genai`, or the `openai` SDK with `base_url` pointed at the compatibility endpoint. We use the `openai` client shape in `llm-kit` for portability, and `google-genai` only when a Gemini-only feature is needed.
- Sources: ai.google.dev/gemini-api/docs/pricing, /docs/rate-limits, /docs/embeddings, /docs/api-key.

### Secondary: Groq (fallback and agent-loop speed)
- **Free tier.** No card. Per model: `openai/gpt-oss-120b`, `gpt-oss-20b`, `qwen/qwen3.8-27b`: 30 RPM, 1,000 RPD, 8K TPM, 200K TPD. Llama 3.x models are no longer free.
- **Why.** Sub-second latency (ideal for agent loops in Phase 3), strict `json_schema` mode and tool use, OpenAI-compatible, different model family from Gemini (teaches portability). Paid is cheap: gpt-oss-20b $0.075/$0.30.
- **Gotcha.** 8K tokens per minute on free is tight for RAG contexts; use Gemini for retrieval-heavy calls.
- Sources: console.groq.com/docs/rate-limits, /docs/structured-outputs.

### Tertiary: OpenRouter `:free` models (model zoo)
- 20 RPM and 50 requests/day free; **1,000 requests/day once you have ever bought $10 of credits** (one-time). Rotating list of free models (recently ~19, including large open models). Same OpenAI schema, one key for nearly every model. Free endpoints are low priority and may log or train; keep the "model training" toggle off.
- Use for `experiments/` comparing many models, not for project traffic.

### Paid later (when justified)
| Provider / model | Price (in/out per 1M) | Why and when |
|---|---|---|
| OpenAI `gpt-5-nano` | $0.05 / $0.40 | Phase 3-4: learn the reference `openai` SDK, Responses API, and strict structured outputs that most tooling targets. Card required. |
| Anthropic Claude Haiku 4.5 / Sonnet 5 | $1 / $5 and $2 / $10 | Phase 3-4 agents: the native `anthropic` SDK is what many agent frameworks and MCP examples target; prompt caching (0.1x reads) and batch (0.5x). |
| DeepSeek V4 Flash (off-peak) | $0.22 / $0.66, 1M context | Bulk offline evals or large batch processing where data residency (China-hosted) is acceptable. Never for anything private. |
| Cloudflare Workers AI | 10,000 neurons/day free; bge-m3 embeddings $0.012/1M; bge-reranker-base $0.003/1M | Cheapest embeddings and reranking at volume if we deploy on Cloudflare. |

### Structured-output portability warning
OpenAI (`strict`), Anthropic (forced tool use / structured outputs), and Gemini (`response_schema`) each support a different JSON-Schema subset. A Pydantic model that works on one can fail on another. `llm-kit` must have a per-provider schema test (Phase 1 lab `providers`).

---

## 2. Embeddings and rerankers

| Need | Local (free, no limits) | Cloud (free tier) | Decision |
|---|---|---|---|
| Embeddings, fast | `nomic-embed-text` via Ollama (137M params, 768 dims, 274 MB, needs `search_query:` / `search_document:` prefixes) or `bge-small-en-v1.5` via `fastembed` (ONNX, 67 MB, no PyTorch) | Voyage AI `voyage-4-lite`: 200M free tokens per model, then $0.02/1M | Phase 2 labs: local. DocPilot RN index: start local, run `experiments/` comparing local vs Voyage on the golden set, choose from measurements. |
| Embeddings, quality | `qwen3-embedding:0.6b` via Ollama (1024 dims, 639 MB, ~10x slower than bge-small) | Voyage `voyage-4` ($0.06/1M) or Gemini `gemini-embedding-2` (free tier) | Same as above. |
| Reranker | `cross-encoder/ms-marco-MiniLM-L6-v2` (80 MB, ~2 ms/pair CPU) for speed; `bge-reranker-v2-m3` Q8 GGUF (606 MB) via `llama-server --reranking` for quality | Voyage `rerank-3-lite` (200M free tokens, then $0.02/1M); Cohere trial capped at 1,000 calls/month | Local first; Voyage when deployed. |

Rules: the same model must embed documents and queries; embedding spaces of different models are incompatible, so a re-embed is required to switch (store `embedding_model` in chunk metadata). Voyage no-card rate limits are UNVERIFIED (historically very low); adding a card lifts them without spend.

---

## 3. Local models on this machine

**Hardware.** Intel i7-8650U (4 cores / 8 threads, AVX2), 16 GB RAM, NVIDIA MX130 2 GB (CUDA compute 5.0: Ollama will try to offload to it and get slower), Intel UHD 620 (Vulkan works but is slower than the CPU), ~22 GB free on each of C: and G:. Memory bandwidth is the ceiling; check whether RAM is dual-channel (Task Manager > Memory > "Slots used"); single-channel roughly halves throughput.

**Runner.** Ollama (OpenAI-compatible endpoint at `http://localhost:11434/v1`, `api_key="ollama"`; chat, streaming, JSON mode, tools, embeddings; `tool_choice` unsupported). Install on G: to protect C:. Add `llama-server` from llama.cpp only for `/v1/rerank`.

**Install and configuration (Phase 0)**
```powershell
# Installer with a custom directory; Ollama's docs state a ~4 GB footprint for the binary install.
.\OllamaSetup.exe /DIR="G:\Ollama"
```
Then set **user** environment variables, quit the tray app, and relaunch:

| Variable | Value | Why |
|---|---|---|
| `OLLAMA_MODELS` | `G:\ollama-models` | Keep weights off C: |
| `CUDA_VISIBLE_DEVICES` | `-1` | Keep the 2 GB MX130 out of inference |
| `OLLAMA_VULKAN` | `0` | Keep the Intel iGPU out of inference |
| `OLLAMA_CONTEXT_LENGTH` | `8192` | Prefill on this CPU is ~30-60 tok/s (estimate); long contexts stall |
| `OLLAMA_KV_CACHE_TYPE` | `q8_0` | Halves KV memory |
| `OLLAMA_FLASH_ATTENTION` | `1` | Faster attention on CPU |
| `OLLAMA_NUM_PARALLEL` / `OLLAMA_MAX_LOADED_MODELS` | `1` / `2` | Avoid RAM pressure |

**Model set (about 5.7 GB, under the 8 GB budget)**

| Model | Size | Role | Estimated decode speed (UNVERIFIED for this CPU) |
|---|---|---|---|
| `qwen3.5:4b` (Apache 2.0, 256K ctx, tools, thinking toggle) | 3.4 GB | Primary local chat and tool-calling | 4-7 tok/s |
| `qwen3:1.7b` (Apache 2.0) | 1.4 GB | Fast tier: classification, extraction, routing experiments | 9-14 tok/s |
| `qwen3-embedding:0.6b` | 0.64 GB | Quality embeddings | fast enough for thousands of chunks |
| `nomic-embed-text` | 0.27 GB | Fast embeddings | very fast |
| Optional: `bge-reranker-v2-m3` Q8_0 GGUF via `llama-server --reranking` | 0.6 GB | Local reranker | ~250 ms per query on CPU |

Alternatives: `phi4-mini` (2.5 GB, MIT, slightly faster than Qwen3-4B) or `hf.co/unsloth/gemma-4-E2B-it-GGUF:Q4_K_M` (3.1 GB; avoid Ollama's official `gemma4:e2b` tag, which is 7.2 GB because it bundles audio and vision encoders). Do not pull 7-9B models: 2-4 tok/s and 7-8 GB resident RAM.

**Realistic use.** Embeddings and reranking: fully practical. 1-2B chat: practical for classification and extraction. 4B chat: fine for batch and single-turn tool calls, slow for interactive sessions. Leave long agent loops, reasoning modes, vision, and >8K contexts to cloud APIs. Run `llama-bench -t 4` once and record real numbers in `EXPERIMENTS.md`.

Sources: docs.ollama.com/gpu, docs.ollama.com/windows, docs.ollama.com/api/openai-compatibility, ollama.com/library/qwen3.5, huggingface.co/Qwen/Qwen3-Embedding-0.6B, github.com/ggml-org/llama.cpp (server README).

---

## 4. Cloud and deployment

### Landscape facts (Sept 2026)
- Fly.io has no free tier (trial only). Koyeb's free tier is closing to new signups after the Mistral acquisition (UNVERIFIED). Hugging Face Gradio/Docker Spaces now require PRO ($9/mo). Netlify Free is 300 credits/month (about 10 deploys plus ~7 GB bandwidth). Oracle Always Free Arm was cut to 2 OCPU / 12 GB and reclaims idle instances.
- Vercel Hobby is contractually **non-commercial**. Fine for learning projects; not for a SaaS with users.
- Cloudflare recommends Workers static assets over Pages for new projects. Python Workers (FastAPI supported) are in open beta but only pure-Python packages work; not our primary backend target.

### Phases 1-3: no credit card
| Layer | Choice | Free limits | Trade-off |
|---|---|---|---|
| API | **Render** free web service (FastAPI in Docker) | 750 instance-hours/month; no free workers or cron; free Postgres expires after 30 days (do not use it) | Spins down after 15 minutes idle, ~1 minute to wake. Acceptable for demos. |
| Frontend | **Vercel Hobby** (Next.js) | 100 GB transfer, 1M edge requests, 100 deploys/day | Non-commercial only |
| Database | **Neon** Postgres free | 0.5 GB per project, 100 compute-hours per project per month, branching, no card, permanent | Autosuspends after 5 minutes idle (~0.5-1 s first query); 100 CU-hours is about 400 hours at 0.25 CU, not 24/7 |
| Vector | pgvector on Neon | included | Fine to hundreds of thousands of vectors within 0.5 GB |
| Cache | **Upstash Redis** free | 500K commands/month, 256 MB | Do not point a polling queue worker at it |
| Schedules / jobs | FastAPI `BackgroundTasks`; **Upstash QStash** (1,000 messages/day, 10 schedules) or **Inngest** Hobby (50K executions/month) | | No always-on worker needed |
| Observability | **Langfuse** Hobby cloud (50K units/month, 30-day retention) or local `arize-phoenix` | | Langfuse is MIT and self-hostable later |
| CI | **GitHub Actions** (public repos free) + **GHCR** | | |

### Phases 4-5: production-shaped, still ~$0
| Layer | Choice | Free limits | Why |
|---|---|---|---|
| API | **Google Cloud Run** (FastAPI container) | Always free: 2M requests, 180,000 vCPU-seconds, 360,000 GiB-seconds, 1 GB egress per month; $300 / 90-day trial for new accounts | Real scale-to-zero with second-scale cold starts (tolerable when LLM calls take seconds anyway); Docker-portable; you already know GCP. **Requires a card**: set `max-instances` to 1-2 and a budget alert. Personal account only. |
| Frontend | **Cloudflare Workers static assets** (Vite/React or Next.js via OpenNext) | unmetered static requests; 100K Worker requests/day | Commercial use allowed |
| Database | Neon (or Supabase free if you want Auth + Storage + pgvector in one box) | Supabase pauses after 7 idle days; Neon does not | |
| Vector | pgvector, same database | | One backup, one connection string. Qdrant free (1 GB) only if p95 latency demands it |
| Cache / rate limiting | Upstash Redis or Cloudflare KV | | |
| Jobs | QStash or Inngest calling back into Cloud Run | | |
| Files | **Cloudflare R2** | 10 GB, zero egress | |
| Observability | Langfuse cloud Hobby; self-host on Oracle Always Free later if retention matters; instrument via OpenTelemetry | | OTel keeps the exit door open |
| CI/CD | GitHub Actions -> GHCR -> Cloud Run deploy | 2,000 private minutes/month | |

Alternatives considered: Railway Free ($1/month usage credit, 1 vCPU / 0.5 GB, no sleep, no card) is a reasonable Render substitute if the 15-minute sleep becomes annoying; AWS Lambda always-free (1M requests) is viable but adds packaging friction for Python dependencies; Azure Container Apps has an equivalent free grant to Cloud Run if a job target is Azure-heavy.

Lock-in posture: Postgres + pgvector, Docker images, OpenTelemetry traces, and S3-compatible R2 are portable. Cloudflare-specific products (D1, KV, Vectorize, Python Workers) stay at the edges.

Sources: render.com/docs/free, railway.com/pricing, docs.cloud.google.com/free/docs/free-cloud-features, vercel.com/docs/plans/hobby, neon.com/pricing, supabase.com/pricing, upstash.com/pricing, developers.cloudflare.com/workers/platform/pricing, langfuse.com/pricing, docs.github.com (Actions billing).

---

## 5. Databases and vector storage

- **PostgreSQL** is the one database to know deeply: relational state, tenants, jobs, traces, full-text search (`tsvector`) for the BM25-ish side of hybrid search, and vectors via **pgvector 0.8.x** (HNSW, iterative scans that fix over-filtering). Locally: Docker `pgvector/pgvector:pg17` in `docker-compose.yml`. Migrations: Alembic. Driver: `asyncpg` via SQLAlchemy 2 async or `psycopg` 3.
- **Hybrid search in Postgres**: `tsvector` + pgvector fused with reciprocal rank fusion in SQL or Python. ParadeDB `pg_search` (true BM25, available on Neon) is a Phase 2 experiment if `tsvector` ranking is not good enough.
- **Dedicated vector DBs**: Qdrant Cloud free cluster (0.5 vCPU, 1 GB RAM, 4 GB disk, free forever) is the comparison target in Phase 2 to learn what a dedicated store gives (filters, payloads, native late-interaction). Pinecone Starter (2 GB, us-east-1 only) and Weaviate free (suspended after 7 idle days, deleted after 30) are not adopted. Chroma is fine as an embedded store for quick labs.
- **Redis** (Upstash free) for caching, rate limiting, and semantic-cache keys in Phase 4.

---

## 6. Frameworks and libraries

Policy: build the concept by hand first, evaluate the framework in `experiments/` against your own implementation, adopt only if it pays for its complexity. Learn 1.x/2.x surfaces only; skip pre-1.0 tutorials (the owned LangChain course included).

| Area | Adopt | When | Why (2026 state) | Skip / later |
|---|---|---|---|---|
| Python toolchain | `uv` (0.12.x), `ruff`, `pytest`, Python 3.12 pinned via `.python-version` | Phase 0 | uv is the de facto standard (surpassed Poetry and pip in CI); FastAPI docs use it. Python 3.12 has the broadest wheel support (onnxruntime, fastembed, torch); the system 3.14 stays for other things | Poetry, pipenv, conda |
| API | **FastAPI** (0.141.x) + Pydantic v2 (2.12.x) + `pydantic-settings` | Phase 1 | Still the greenfield default for LLM backends; Litestar 3 unreleased | Django Ninja unless already in Django |
| HTTP / async | `httpx`, `asyncio`, `respx` for tests | Phase 1 | | |
| LLM clients | `openai` SDK against OpenAI-compatible endpoints (Gemini, Groq, OpenRouter, Ollama); `google-genai` for Gemini-only features; `anthropic` when we pay for Claude | Phase 1 | Learn both API shapes: Chat-Completions-style (everyone) and Responses-style (OpenAI; Assistants API was sunset 2026-08-26) | |
| Frontend AI UI | **Vercel AI SDK 7** (`useChat`, `streamText`, UI message stream protocol; Node 22+, ESM-only) | Phase 2 | The frontend streaming standard; maps directly to your React strength; backend can be Python via a custom transport / SSE | Mastra (all-TS agents) later if a TS-only stack is wanted |
| Agents | Hand-written loop first; then **Pydantic AI** (2.x; typed, DI, provider-agnostic, feels like Zod + tRPC); then **LangGraph 1.x** (+ LangChain 1.x `create_agent` surface, LangSmith awareness) | Phase 3 | Pydantic AI is the most readable end to end; LangGraph is what job postings name most (durable state, interrupts, human-in-the-loop, checkpointers) | CrewAI, Google ADK, Microsoft Agent Framework, Haystack, smolagents (read its source once), OpenAI Agents SDK (docs only), Claude Agent SDK (Phase 5 if coding-agent shaped) |
| Protocols | **MCP** (spec 2026-07-28, stateless redesign; pin SDK versions; Python `mcp`/FastMCP) | Phase 3 | Under the Linux Foundation's Agentic AI Foundation; standard for tool servers; appears in senior postings | A2A (cross-organisation agent federation) later |
| Document parsing | `pymupdf4llm` (fast, text-first PDFs); **Docling** (layout-aware PDF to Markdown/JSON) | Phase 2 | Docling leads self-hosted parsing in 2026 | Unstructured platform, MarkItDown (know them) |
| Chunking | LangChain text splitters or **Chonkie**; own structure-aware splitter for Markdown/code | Phase 2 | Contextual retrieval and late chunking are the interview-grade upgrades | |
| RAG framework | None as app framework; **LlamaIndex** (0.14.x) read and tried in one experiment to learn index/synthesizer vocabulary | Phase 2 | | |
| Evals | Own harness in `llm-kit` first; **DeepEval** (pytest-style) or **RAGAS** (faithfulness, context precision/recall) as CI gate; `promptfoo` for red-teaming matrices | Phase 1 (own), Phase 2 (RAGAS), Phase 4 (CI) | One code-first CI gate plus one platform is the standard pairing | Braintrust (know it; the owned course uses it) |
| Observability | **Langfuse** (MIT, ClickHouse-owned since Jan 2026, self-hostable); OpenTelemetry concepts (GenAI semantic conventions are still unstable, pin versions, do not hand-roll attributes) | Phase 2 tracing, Phase 4 depth | Free, vendor-neutral, in postings | LangSmith (use when on LangGraph jobs), Arize Phoenix (good OSS alternative) |
| Background jobs | FastAPI `BackgroundTasks` -> **Taskiq** or **arq** (async-native, Redis) | Phase 3-4 | LLM jobs are I/O-bound and long-running; Celery vocabulary for interviews only | Celery, Dramatiq |
| Prompt optimisation | DSPy / GEPA | Phase 5 optional | Needs an eval metric first | |

---

## 7. Project structure

**This repo (`ai-engineering-journey`)**: documentation, `labs/`, `experiments/`, `notes/`, `.claude/agents/`, and `packages/llm-kit`.

**Each major project** (own repo under saad-official):
```
project/
  README.md                 # what, why, demo, quick start, architecture, evals, costs, status
  pyproject.toml  uv.lock  .python-version  .env.example  Dockerfile  docker-compose.yml
  app/
    main.py                 # FastAPI app factory, routers, middleware
    api/                    # routers, request/response models
    core/                   # settings, logging, errors, auth
    llm/                    # provider layer (llm-kit usage), prompts/ (versioned), schemas
    retrieval/              # ingestion, chunking, embeddings, search (Phase 2+)
    agents/                 # tools, loop, memory, approvals (Phase 3+)
    db/                     # models, migrations (alembic/), repositories
    workers/                # background jobs, schedules
  evals/                    # golden sets (jsonl), scorers, run_evals.py, results/
  tests/                    # pytest; recorded provider responses under tests/fixtures
  frontend/                 # Next.js (Vercel AI SDK), when the project has a UI
  docs/                     # architecture.md, decisions/, setup.md, api.md, evals.md, costs.md, security.md, lessons.md, future.md
  .github/workflows/        # ci.yml (lint, test), evals.yml (scheduled), deploy.yml
```

---

## 8. Industry relevance (Sept 2026, informs priorities)

- "AI Engineer" is the #1 rising title (LinkedIn 2026, postings +143% YoY); "Forward Deployed Engineer" / "Applied AI Engineer" is the fastest-growing variant. A US analysis of 43,480 postings (Jan-Jul 2026) found a $176K median salary, 66% IC roles, and more hiring from professional services and large enterprises than from tech companies.
- Most requested skills, in rough order: Python; cloud (AWS/GCP/Azure) and Docker; foundation-model APIs; RAG design (chunking, embeddings, hybrid search, reranking); agents and orchestration (LangGraph named most); evals (RAGAS, DeepEval, LangSmith); vector databases; observability; SQL/Postgres; FastAPI and async streaming; TypeScript + React for frontend-facing AI roles; structured outputs and Pydantic; MCP in senior roles; customer-facing communication.
- Full-stack + AI is explicitly in demand: full-stack postings now expect LLM integration, RAG, and light agents in user-facing features. Your frontend and mobile depth is a differentiator, not a detour.
- What hiring managers value in portfolios: document Q&A with citations and failure handling; structured extraction with measured accuracy; a bounded tool-calling agent with memory and error recovery; an eval pipeline in CI; all deployed behind FastAPI + Docker with tracing and cost per request. This roadmap's four projects map onto exactly these.
- Common interview topics: validating a model upgrade; diagnosing confident-but-wrong RAG answers; when not to build an agent; bounded loops and budgets; halving cost without losing quality; two-stage retrieval; MCP vs function calling; structured output vs tool call; observability stack; prompts as versioned code.

---

## 9. Verify-on-signup checklist

Record the real values here once you have accounts:
- [ ] Gemini free-tier RPM/RPD/TPD as shown in AI Studio (new-style key created)
- [ ] Groq limits as shown in the console
- [ ] Voyage AI no-card rate limits
- [ ] Render free instance CPU/RAM (UNVERIFIED: ~0.1 CPU / 512 MB)
- [ ] Neon compute-hours meter after the first week of use
- [ ] `llama-bench` numbers for `qwen3.5:4b` and `qwen3:1.7b` on this CPU; RAM channel configuration

## Decision log

| Date | Decision | Context | Alternatives | Consequences |
|---|---|---|---|---|
| 2026-09-05 | Gemini primary, Groq secondary, OpenRouter zoo, Ollama local | Only Gemini offers chat + embeddings + structured outputs free without a card; Groq adds speed and a second model family | OpenAI (paid only), Mistral free (limits unpublished, phone + training opt-in), Cerebras/SambaNova (too limited) | Never send private data via free tiers; provider layer must be swappable; add paid OpenAI/Anthropic in Phase 3-4 for SDK literacy |
| 2026-09-05 | Postgres + pgvector as the only datastore through Phase 4 | Simplicity, portability, hybrid search in one place, free on Neon | Qdrant/Pinecone/Weaviate | Learn pgvector limits by measurement; Qdrant comparison experiment in Phase 2 |
| 2026-09-05 | Render + Vercel Hobby early, Cloud Run + Cloudflare later | No card for learning; commercial-capable, always-free compute for a real MVP | Railway free, AWS Lambda, Azure Container Apps, Fly (no free tier) | Accept Render sleep in demos; add card and budget alert for Cloud Run in Phase 4 |
| 2026-09-05 | No agent framework until Phase 3; Pydantic AI before LangGraph | Understand the loop first; Pydantic AI most readable, LangGraph most demanded | LangGraph-first, CrewAI, ADK | Frameworks evaluated in `experiments/langgraph-vs-mine` against own implementation |
| 2026-09-05 | Vercel AI SDK 7 for AI UI | Frontend strength; standard streaming primitives | Hand-rolled SSE client only | Backend must emit a compatible stream or use a custom transport |
| 2026-09-05 | Langfuse for tracing | MIT, self-hostable, vendor-neutral, common in postings | LangSmith, Braintrust, Phoenix | Instrument through OpenTelemetry where possible |
