# AI Engineering Journey

Personal workspace for moving from Senior Frontend / Full-Stack Engineer to Full-Stack AI Engineer: structured learning, hands-on labs, experiments, and a small number of deployed, documented portfolio projects. Everything here is personal work under [github.com/saad-official](https://github.com/saad-official), separate from any employer.

**Status:** Phase 0 (setup). Started 2026-09-05.

## Start here

| Document | What it answers |
|---|---|
| [AI_ENGINEERING_ROADMAP.md](AI_ENGINEERING_ROADMAP.md) | The phases: objectives, concepts, labs, projects, exit criteria, interview readiness |
| [PROJECTS.md](PROJECTS.md) | The project ladder and the 12-question evaluation of each major project |
| [LEARNING_PLAN.md](LEARNING_PLAN.md) | Weekly rhythm, owned courses mapped to phases (do / skip / practise), progress tracker |
| [TECHNOLOGY_STACK.md](TECHNOLOGY_STACK.md) | Every provider, cloud, database, and framework decision with verified cost and rationale |
| [ARCHITECTURE_NOTES.md](ARCHITECTURE_NOTES.md) | Reference architectures the projects instantiate |
| [AI_CONCEPTS.md](AI_CONCEPTS.md) | Knowledge-base index and the note template (`notes/concepts/`) |
| [EXPERIMENTS.md](EXPERIMENTS.md) | Experiment log with numbers and decisions |
| [CAREER_PLAN.md](CAREER_PLAN.md) | GitHub baseline audit, evidence ledger, resume and interview plan |
| [CLAUDE.md](CLAUDE.md) | Working rules for AI-assisted sessions in this workspace |

## Decisions at a glance (verified 2026-09-05, details in TECHNOLOGY_STACK.md)

| Question | Decision |
|---|---|
| LLM provider | Google Gemini API free tier (primary), Groq free (secondary), OpenRouter `:free` (model zoo) |
| Cheapest dev setup | All free tiers, no credit card, through Phase 3. First justified spend: one-time $10 OpenRouter top-up |
| Local models | Ollama on G: with Qwen3.5-4B, Qwen3-1.7B, Qwen3-Embedding-0.6B, nomic-embed-text (about 5.7 GB) |
| Cloud | Render + Vercel Hobby for learning; Google Cloud Run always-free + Cloudflare for the production-shaped SaaS |
| Database | PostgreSQL on Neon (pgvector included); Docker locally |
| Vector database | pgvector; Qdrant free cluster as a comparison experiment only |
| Frameworks | None in Phases 1-2 (thin `llm-kit`); Vercel AI SDK 7 on the frontend; Pydantic AI then LangGraph 1.x in Phase 3; MCP; Langfuse; DeepEval/RAGAS |
| Deployment stack | uv, Docker multi-stage, GitHub Actions, GHCR, Neon, Upstash Redis, QStash/Inngest, Cloudflare R2 |
| Project structure | This repo for docs, labs, experiments, `packages/llm-kit`; one repo per major project |
| First project | `labs/01-hello-llm`, then Changelog Forge (AI release-notes generator) |

## Project ladder

1. **Changelog Forge** (Phase 1): structured outputs, chunking, model routing, evals, GitHub Action.
2. **DocPilot RN** (Phase 2): version-aware RAG over React Native / Expo docs with hybrid search, reranking, citations, streaming UI.
3. **Review Radar** (Phase 3): app-store review intelligence agent with tools, memory, human-in-the-loop, schedules, MCP server.
4. **Review Radar SaaS** (Phase 4): multi-tenant, observable, evaluated in CI, deployed.
5. **Chosen product** (Phase 5): full-stack AI SaaS with real users.

## The team (Claude Code subagents in `.claude/agents/`)

`mentor` teaches and checks understanding. `architect` designs systems and records decisions. `pm` plans milestones and check-ins. `reviewer` reviews code for LLM-specific pitfalls. `researcher` verifies current tools and prices. `qa` designs tests and evals. `product-strategist` scores product ideas and unit economics. `devops` handles Docker, CI/CD, deployment, monitoring.

## Phase 0 checklist (week 1)

Machine: Windows 10, i7-8650U, 16 GB RAM, ~22 GB free per drive. Keep caches and models on G:.

- [x] Git identity (done 2026-09-05): this repo is initialised; `~/.gitconfig` has an `includeIf` so any repo under `G:\AI Engineering Journey\` or `G:\personal\` automatically uses the saad-official identity from `~/.gitconfig-personal`; everything else keeps the work identity. `G:\` itself is a git repository root (unrelated Xcode commits); this folder is its own nested repo.
- [ ] GitHub CLI: log in the personal account once (interactive, opens the browser), then switching is one command:
  ```powershell
  gh auth login -h github.com -p https -w
  ```
  Then `.\scripts\git-account.ps1 personal` or `work` (wraps `gh auth switch`). Personal repos use HTTPS remotes (auth follows the active `gh` account); work repos keep SSH remotes (auth via SSH key, unaffected by switching).
- [x] `uv` 0.12 installed; Python 3.12 installed under `G:\uv-python`; `UV_CACHE_DIR` and `UV_PYTHON_INSTALL_DIR` point at G:.
- [x] API keys for Gemini, Groq, OpenRouter are in `.env` (gitignored) and verified by `labs/01-hello-llm`. Use `.\scripts\add-secret.ps1 -Name NAME` to add or rotate a key without it appearing in chat or shell history. Still to do: record the live Gemini free-tier limits from AI Studio in `TECHNOLOGY_STACK.md` section 9.
- [ ] Ollama: user env vars are set (`OLLAMA_MODELS=G:\ollama-models`, `CUDA_VISIBLE_DEVICES=-1`, `OLLAMA_VULKAN=0`, context/KV tuning). Install to `G:\Ollama` with `OllamaSetup.exe /DIR="G:\Ollama"`, then:
  ```bash
  ollama pull qwen3.5:4b && ollama pull qwen3:1.7b && ollama pull qwen3-embedding:0.6b && ollama pull nomic-embed-text
  ```
- [x] `labs/01-hello-llm` created and run against Gemini, Groq, OpenRouter (Ollama pending). Results in `EXPERIMENTS.md` exp-001.
- [ ] Create `packages/llm-kit` skeleton (Phase 1, week 2).
- [ ] Create the `saad-official/saad-official` profile README and push this repo as `saad-official/ai-engineering-journey`.
- [ ] Watch Frontend Masters lessons 1-4 and DataCamp "LLM Concepts" (see `LEARNING_PLAN.md`).
- [ ] Prune Docker images and volumes (`docker system df`, `docker system prune`) to free disk before Phase 2's Postgres work.
