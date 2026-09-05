# Projects

The portfolio ladder. Few projects, each one proving a specific AI Engineering capability, each reusing the last. Every major project must answer the 12 questions before code is written.

## The 12 questions (answer for every major project)

1. What problem are we solving?
2. Who would use it?
3. Why does AI actually add value (vs. a regex, a rule, or a human)?
4. What makes it different from what exists?
5. Can it become a SaaS? What would people pay for?
6. What is the MVP (one sentence) and what is explicitly not in it?
7. What is the architecture?
8. Which AI components are involved (prompting, structured output, RAG, agents, evals)?
9. What does it cost to run (per request, per user per month)?
10. How would we scale it?
11. How do we evaluate the AI output?
12. What makes it impressive to a potential employer?

## Ladder

| Level | Project | Phase | Repo | Status |
|---|---|---|---|---|
| 0 | Labs and experiments | 0-5 | `ai-engineering-journey` (this repo) | In progress |
| 1 | Changelog Forge | 1 | `changelog-forge` | Planned |
| 2 | DocPilot RN | 2 | `docpilot-rn` | Planned |
| 3 | Review Radar | 3 | `review-radar` | Planned |
| 4 | Review Radar SaaS (hardened, deployed, multi-tenant) | 4 | `review-radar` | Planned |
| 5 | Chosen product (see roadmap Phase 5) | 5 | TBD | Not started |

Shared internal library: `packages/llm-kit` in this repo (thin provider layer, cost accounting, structured outputs, tool loop, eval helpers). Published later as a private-ish package or vendored; it exists to be understood, not to compete with frameworks.

Rules: no generic chatbot, no todo app, no weather bot except as a lab. No projects in the employer's domain (therapy, mental-health SaaS, Zoom apps for therapists). Every project: README, architecture, setup, `.env.example`, API docs, screenshots or GIF, decisions, lessons learned, future work, `costs.md`, `evals/`.

---

## Level 1: Changelog Forge

**One-liner.** Turn a git range into audience-specific, categorised release notes with links, via CLI, API, and a GitHub Action.

1. **Problem.** Writing release notes is tedious, skipped, or low quality. Commit messages and PR titles contain the facts but not the narrative, and nobody wants to read 200 commits.
2. **Users.** Open-source maintainers, small product teams, indie developers publishing app updates (App Store "What's New" text is a natural output).
3. **Why AI.** Categorisation, deduplication of related commits, translating developer language into user language, and detecting breaking changes need language understanding. Rules cannot do it; humans do not want to.
4. **Differentiator.** Two audiences from one run (end-user and developer notes), explicit breaking-change detection with confidence, links preserved to every source commit/PR, deterministic-enough output via structured schemas, and a measured eval suite. Runs as a GitHub Action with a comment on the release PR.
5. **SaaS potential.** Moderate. Hosted version with GitHub App install, per-repo history, App Store / Play Console publishing of "What's New" text. Free for public repos, paid for private orgs.
6. **MVP.** `changelog-forge <repo> <from>..<to>` prints Markdown release notes with categories and links. Not in MVP: web UI, GitHub App, store publishing, translations.
7. **Architecture.** CLI (Typer) -> collector (git log / GitHub API via `httpx`) -> normaliser (commits + PR titles/bodies -> `ChangeItem` models) -> chunker (token-aware groups) -> map stage (cheap model classifies and summarises each group into structured `Change` objects) -> reduce stage (better model merges, dedupes, writes prose per audience) -> renderer (Markdown/JSON) -> outputs (stdout, FastAPI endpoint, GitHub Action comment). All LLM calls via `llm-kit` with cost logging.
8. **AI components.** Prompt templates versioned in repo; structured outputs (Pydantic); model routing (cheap vs capable); map-reduce over large inputs; eval harness with code-based scorers.
9. **Costs.** Target under $0.01 per 100 commits on free/cheap models; measured and published in `costs.md`. Free tier of the primary provider should cover all development.
10. **Scale.** Stateless API; queue long ranges; cache per commit SHA so re-runs only process new commits.
11. **Evaluation.** Golden set: 10 real public repo ranges with hand-curated expected items (breaking changes, notable features, PR links). Scorers: coverage of expected items, no hallucinated PR numbers (regex + verification against the API), category accuracy, link validity, length budget. LLM-judge only for prose quality with a rubric.
12. **Employer appeal.** Shows disciplined LLM integration: schemas, routing, chunking, evals, cost tracking, CI packaging. Small but production-shaped.

**Milestones.** M1 collector + models + CLI skeleton. M2 single-shot generation with structured output. M3 chunking + map-reduce + routing. M4 eval harness + golden set. M5 FastAPI endpoint + GitHub Action + README/GIF + release.

---

## Level 2: DocPilot RN

**One-liner.** Version-aware documentation assistant for React Native / Expo: grounded answers with citations for the SDK version you are actually on, plus "what changed between versions".

1. **Problem.** RN/Expo docs change fast; answers found online target other versions; developers waste hours on version drift.
2. **Users.** React Native / Expo developers (a community you belong to), later any team with versioned SDK docs.
3. **Why AI.** Natural-language questions over large, structured, versioned docs; synthesising across pages; explaining diffs between versions. Search alone returns pages, not answers.
4. **Differentiator.** Version pinning via metadata filtering, structure-aware chunking that never splits code blocks, hybrid search for exact API names, reranking, cross-version diff answers, verified citations rendered in the UI, published eval numbers.
5. **SaaS potential.** Moderate as a vertical; higher as "bring your own versioned docs" for SDK vendors and internal platform teams.
6. **MVP.** Ask a question, pick an SDK version, get a streamed grounded answer with clickable citations, over two Expo SDK versions. Not in MVP: auth, uploads, cross-version diff, multiple SDKs.
7. **Architecture.** Ingestion worker (fetch docs -> parse Markdown/HTML -> structure-aware chunks with metadata {sdk, version, path, heading, url} -> embed -> pgvector + full-text index; idempotent by content hash) -> FastAPI query service (query rewrite -> hybrid retrieval with version filter -> rerank -> context assembly with citation IDs -> streamed generation -> citation verification) -> Next.js UI (chat, version selector, citation panel) -> eval harness (golden Q/A per version).
8. **AI components.** Embeddings (local or API, decided in `TECHNOLOGY_STACK.md`), pgvector, hybrid + RRF, cross-encoder reranker, RAG prompt with grounding and refusal, streaming, RAG evals (recall@k, faithfulness, citation accuracy).
9. **Costs.** Embedding a few thousand pages once is cents or free locally; queries on a cheap model are fractions of a cent; free Postgres tier suffices for the corpus.
10. **Scale.** Ingestion as a queue; embeddings cached by content hash; read replicas or a dedicated vector DB only if p95 latency demands it.
11. **Evaluation.** 40-question golden set spanning versions with expected source URLs; retrieval recall@5 and MRR; answer faithfulness via judge rubric; citation URL correctness by code; regression run after every chunking or model change; results table in README.
12. **Employer appeal.** A real RAG system with measurable quality, hybrid retrieval, reranking, and a polished streaming UI. The version-diff feature is a memorable talking point.

**Milestones.** M1 ingestion of one version into pgvector. M2 minimal RAG with citations (CLI). M3 hybrid + rerank + evals. M4 FastAPI streaming + Next.js UI. M5 second version + version filter + diff answers. M6 deploy + docs.

---

## Level 3: Review Radar

**One-liner.** An agent that reads public app-store reviews for a mobile app, clusters them into themes, extracts structured signals, drafts replies and GitHub issues, and waits for human approval before acting.

1. **Problem.** Small mobile teams cannot keep up with reviews; signal (crash on a device, a top feature request) is buried in noise; replies are late or absent.
2. **Users.** Indie developers and small mobile teams; product managers of mobile apps.
3. **Why AI.** Theme clustering, structured extraction (bug vs request, sentiment, device/OS/version), and drafting empathetic, policy-compliant replies require language understanding at volume.
4. **Differentiator.** Agentic but safe: every write action (reply, issue) is proposed, explained, and approved by a human; memory of what was already triaged; evidence links to source reviews; scheduled runs; measurable extraction accuracy.
5. **SaaS potential.** High. Existing tools are dashboards; an AI-native, approval-driven agent with GitHub/Jira integration is a clear product. Per-app pricing.
6. **MVP.** For one public app: fetch new reviews daily, cluster, extract signals, show a dashboard with proposed replies and issues, approve/reject, create GitHub issues on approval. Not in MVP: posting replies to stores (needs developer credentials), multi-tenant, billing.
7. **Architecture.** Scheduler (cron on the chosen platform) -> agent worker (tools: `fetch_app_store_reviews`, `fetch_play_reviews`, `search_memory`, `cluster_reviews`, `draft_reply`, `propose_issue`) -> Postgres (reviews, clusters, proposals, approvals, trajectories) -> FastAPI (approval API) -> Next.js dashboard -> executors for approved actions (GitHub API). Embeddings from Phase 2 for clustering and memory. Trajectory logs for evaluation.
8. **AI components.** Agent loop with budgets, tool design, structured extraction, embeddings clustering, long-term memory, human-in-the-loop with persisted paused state, background execution, an MCP server exposing the tools, agent evals (trajectory + outcome).
9. **Costs.** Reviews are short; a few hundred reviews per day costs cents on cheap models; clustering with local embeddings is free. Target under $1/app/month at MVP volumes.
10. **Scale.** Per-app jobs on a queue; batch API for non-urgent analysis; rate limiting per store API; sharded schedules.
11. **Evaluation.** Labelled set of 200 reviews (category, sentiment, has-device-info) for extraction accuracy; cluster quality by human spot-check and silhouette-like metrics; trajectory evals (right tools, right args, no unapproved writes); reply quality rubric (tone, policy compliance, no promises).
12. **Employer appeal.** A production-shaped agent with safety controls, memory, scheduling, and a dashboard. Demonstrates judgement about when agents are appropriate.

**Milestones.** M1 fetch tools + storage + dedupe. M2 extraction + clustering, CLI report. M3 agent loop + memory + trajectory logs. M4 approval queue API + dashboard. M5 scheduled deployment + GitHub executor. M6 evals + MCP server + docs.

---

## Level 4: Review Radar SaaS

Same product, made real: sign-up and tenant isolation, connect multiple apps, queue-backed workers, caching, observability with per-tenant cost, eval suite in CI, security hardening (injection via review text is a live threat here), Docker + CI/CD + cloud deployment, runbook, `costs.md` with real numbers. Milestones and details in the roadmap Phase 4 and the project's `docs/`.

---

## Level 5: Chosen product

Selected in Phase 5 via the product-strategist process. Candidate seeds are listed in the roadmap. Fill in the 12 questions here once chosen.

---

## Project documentation checklist (copy into each repo)

- [ ] README: what, why, demo GIF/screenshots, quick start, architecture diagram, eval results, costs, status
- [ ] `docs/architecture.md`: components, data flow, state, failure modes
- [ ] `docs/decisions/NNNN-*.md`: Context / Options / Decision / Consequences
- [ ] `docs/setup.md` and `.env.example`
- [ ] `docs/api.md` (or link to OpenAPI)
- [ ] `docs/evals.md`: golden set description, scorers, latest results
- [ ] `docs/costs.md`: measured cost per request / per user
- [ ] `docs/security.md` (from Level 3 up)
- [ ] `docs/lessons.md` and `docs/future.md`
