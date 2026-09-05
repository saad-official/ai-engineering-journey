# Learning Plan

Courses give theory. This workspace gives skill. Rule: no more than about a third of weekly time on video; the rest is building, breaking, documenting.

## Weekly rhythm (8-12 hours)

| Block | Time | What |
|---|---|---|
| Theory | 2-3 h | Course modules mapped to the current phase (below), taking notes straight into `notes/concepts/` drafts |
| Build | 5-7 h | Current lab or project milestone, AI-assisted, with the "explain it back" check at the end |
| Reflect | 1 h | Update `EXPERIMENTS.md`, finish one concept note, run the `reviewer` or `qa` agent on the week's code, adjust plan with the `pm` agent |

Weekend-heavy schedules are fine; consistency beats intensity. Log each week in the tracker at the bottom.

## Owned courses mapped to the roadmap

Location: `G:\courses\AI-Engineeering`. Vintage matters: the DataCamp material is from 2023-2024 and is OpenAI-centric and pre-LangChain-1.0; treat it as concept theory and follow its code against an OpenAI-compatible endpoint from our primary free provider (change `base_url` and `model`), which is itself a useful exercise in provider abstraction.

### Bundle A: AI Fundamentals (DataCamp, 2023-2024)

| Course | Roadmap topics | Do | Skip | Practice |
|---|---|---|---|---|
| Understanding Artificial Intelligence | Landscape vocabulary | Skim in one sitting during Phase 0 if you want the vocabulary; otherwise skip | Most of it; you already work in software | None |
| Understanding Machine Learning | ML vs LLM distinction, train/test, overfitting, evaluation mindset | Chapters on evaluation and generalisation (Phase 0-1) | Classical model zoo | Relate "held-out test set" to our golden eval sets |
| Generative AI Concepts | How generative models differ, risks, use cases | Watch once in Phase 0 | Business-strategy sections | None |
| Large Language Models (LLMs) Concepts | Tokens, transformers at a high level, pre-training vs fine-tuning, limitations | Whole course, Phase 1 week 1; this is the theory backbone for labs 02-04 | None | Labs `tokens`, `params`; write `notes/concepts/tokens-and-context-windows.md` |
| Learn ChatGPT | Consumer prompting | Skip | All | None |
| AI Ethics | Bias, privacy, accountability | One pass in Phase 4 alongside the security/privacy work | None | Feed into `docs/security.md` of Review Radar |

### Bundle B: Associate AI Engineer for Developers (DataCamp, 2024)

| Course | Roadmap topics | Do | Skip | Practice |
|---|---|---|---|---|
| Software Engineering Principles in Python | Modularity, packaging, docs, testing | Whole course in Phase 1 weeks 1-2; you know the principles, learn the Python idioms | Nothing, it is short | Apply to `llm-kit` packaging and tests |
| Working with the OpenAI API | Chat completions, roles, parameters, moderation, audio | Phase 1; do the code against the OpenAI-compatible endpoint | Deprecated Completions endpoint bits; audio unless curious | Labs `params`, `structured`, `stream` |
| ChatGPT Prompt Engineering for Developers | Prompt patterns, few-shot, chain of thought, structured prompting | Phase 1; skim, then apply | Marketing-style prompt tips | Prompt templates in Changelog Forge; `prompt-lab` |
| Developing AI Systems with the OpenAI API | Function calling, error handling, moderation, testing, safety | Phase 1 weeks 3-4; the closest course to real engineering | Anything OpenAI-account-specific | Lab `tools`, `retry`; Changelog Forge M2-M3 |
| Introduction to Embeddings with the OpenAI API | Embeddings, similarity, semantic search, recommendations | Phase 2 week 1 | OpenAI-specific pricing content | Labs `embed-explore`, `chunk-compare` with a local embedding model |
| Vector Databases for Embeddings with Pinecone | Vector DB concepts, indexes, metadata, namespaces | Phase 2 weeks 2-3 for the concepts only; implement on pgvector, not Pinecone | Pinecone-specific ops | Lab `pgvector-basics`, `hybrid` |
| Developing LLM Applications with LangChain | Chains, retrievers, RAG, agents in LangChain (older API) | Phase 3 week 6, after your own loop exists; watch to understand what frameworks abstract | Deprecated APIs; do not adopt its patterns wholesale | Experiment `langgraph-vs-mine` |
| Working with Hugging Face | Hub, pipelines, tokenizers, datasets | Phase 2 week 1 (tokenizers, local embedding models) and when choosing rerankers | Fine-tuning sections for now | Local embeddings and reranker labs |
| LLMOps Concepts | Lifecycle, monitoring, evaluation, deployment, cost | Phase 4 week 1; good framing for production work | None | `notes/concepts/llm-observability.md`, `evals-in-ci.md` |

### Bundle C: Frontend Masters, AI Engineering Fundamentals (2026, TypeScript, Cloudflare Agents)

Modern and closest to industry practice, but TypeScript- and Cloudflare-centric. Use it for mindset and frontend integration; implement the backend concepts in Python.

| Lessons | Roadmap topics | Do | Practice |
|---|---|---|---|
| 1-4 Introduction, What is an AI Engineer, Project Tour, Agent Overview | Role definition, agent mental model | Phase 0 (all four) | Write your own definition in `CAREER_PLAN.md` |
| 5-9 Zod schemas, tools, coding an agent, chat message, Cloudflare Agent Q&A | Schemas as contracts, tool definitions, agent loop | Phase 1 (5-6 for schemas and tools), Phase 3 (7-9) | Lab `tools`, `loop-from-scratch`; note how Zod maps to Pydantic |
| 10-16 useAgent hooks, canvas, messages UI, chat panel, wiring | Streaming chat UI in React | Phase 2 when building the DocPilot UI | Reuse ideas with Vercel AI SDK or your own SSE client |
| 17-25 Why evals matter, scoring, eval harness, looping cases, Braintrust, code-based scorers | Evaluation design | **Phase 1 week 4, early on purpose**; revisit in Phase 2 and 4 | `prompt-lab`, Changelog Forge eval harness; consider Braintrust's free tier vs Langfuse per `TECHNOLOGY_STACK.md` |
| 26-31 Context engineering, baseline, rewriting system prompt, serialising canvas, canvas data in context | Context management, prompt iteration with evals | Phase 1-2 | Changelog Forge prompt iterations measured by evals |
| 32-39 Improving tools, client-side tools, web search tool, troubleshooting regressions | Tool design and regression discipline | Phase 3 | Lab `tool-design` |
| 40-44 Improvement loop, diagram eval, schemas, simulator | Iteration loop, schema vocabulary | Phase 3-4 | Review Radar extraction schemas |
| 45-48 RAG, RAG with Upstash, corpus and retrieval tool, indexing queries | RAG as a tool for an agent | Phase 2 end / Phase 3 | DocPilot retrieval exposed as a tool to the Review Radar agent |
| 49 Wrap-up | | | |

### Pluralsight (active subscription)

Use for targeted gaps, not for browsing. Pick one path per phase and only the modules that map to the exit criteria:
- Phase 1: a modern Python path (async, typing, packaging, testing) and a FastAPI fundamentals course.
- Phase 2: PostgreSQL fundamentals (indexes, full-text search) if needed.
- Phase 4: Docker and GitHub Actions courses; a security fundamentals course covering OWASP for APIs.
Record the specific courses chosen in the tracker below when you pick them.

### Gaps not covered by owned courses (fill with docs, mentor sessions, and labs)

Hybrid search and reranking; RAG evaluation methodology; agent design without frameworks; human-in-the-loop and durable execution; MCP; LangGraph / Pydantic AI (current versions); production concerns (multi-tenancy, caching, observability, prompt injection defence, cost controls); cloud deployment of Python services; local model inference. The `researcher` agent should produce a brief before each of these is started so we learn the current state, not the 2024 state.

## Progress tracker

| Week | Dates | Phase | Planned | Done | Blockers / notes |
|---|---|---|---|---|---|
| 1 | 2026-08-31 to 09-06 | 0 | Setup, hello-llm, provider keys, repo pushed | Done: uv toolchain, `labs/01-hello-llm` against Gemini/Groq/OpenRouter, exp-001 logged, `TECHNOLOGY_STACK.md` verified, repo pushed to `saad-official/ai-engineering-journey` (public) | Ollama not installed yet - carried into Phase 1 as a stretch item, hard deadline week 3 |
| 2 | 2026-09-07 to 09-13 | 1 | Theory: DataCamp "LLMs Concepts" ch. 1-4 (~2.5 h). Build: `labs/02-tokens` (local tokenizer vs provider `usage` for 5 texts; Gemini latency re-measured over 10 calls) and `labs/03-params` (1 prompt x temp 0/0.7/1.2 x 5 runs on Groq). Reflect: `EXPERIMENTS.md` exp-002 + exp-003 rows and an exp-001 amendment; `notes/concepts/tokens-and-context-windows.md`; `reviewer` agent pass. Stretch: Ollama install on G: (time-boxed 45 min). Plan: `notes/plans/phase1-week1.md` | | |

## Phase exit checklist

Before moving on: exit criteria in the roadmap met, major project deployed and documented, concept notes written, `EXPERIMENTS.md` updated, a 10-minute spoken explanation of the project recorded or rehearsed with the `mentor` agent.
