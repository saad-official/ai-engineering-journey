# Career Plan

Activated in earnest around week 20 (Phase 4), because a career narrative needs projects behind it. Until then this file collects material.

## Positioning

**Statement to earn:** "I am a Senior Software Engineer who designs, builds, integrates, deploys, and operates modern AI-powered applications."

**Likely best-fit titles** (decide from actual strengths at week 20, not from wishful thinking): Full-Stack AI Engineer, AI Application Engineer, Applied AI Engineer, Forward Deployed Engineer (AI), LLM Engineer. Less likely fits: AI Platform Engineer (infra-heavy), ML Engineer (training-heavy).

**Differentiators to lean on:** senior product-facing frontend and mobile experience (rare among AI engineers), real UX judgement, full-stack ownership, and projects that are deployed and evaluated rather than notebooks.

## Evidence ledger (append as projects ship)

| Capability | Evidence (project, link, metric) |
|---|---|
| LLM API integration, structured outputs | Changelog Forge: |
| Context management, map-reduce | Changelog Forge: |
| Cost discipline | Changelog Forge `costs.md`: |
| Embeddings, hybrid search, reranking | DocPilot RN: |
| RAG evaluation | DocPilot RN eval table: |
| Streaming AI UI in React/Next.js | DocPilot RN UI: |
| Agent loop, tool design, memory | Review Radar: |
| Human-in-the-loop, scheduled agents | Review Radar: |
| MCP server | Review Radar tools: |
| Multi-tenancy, auth, queues, caching | Review Radar SaaS: |
| Observability, evals in CI | Review Radar SaaS: |
| Security (prompt injection defence) | Review Radar `security.md`: |
| Cloud deployment, Docker, CI/CD | All projects: |
| Product thinking, unit economics | Phase 5 product `business.md`: |

## Deliverables and timing

| Week | Deliverable |
|---|---|
| 20 | GitHub profile README for saad-official: one paragraph, four project cards with architecture thumbnails, links to live demos |
| 22 | Draft AI-focused resume: outcomes and metrics per project; existing senior experience framed around product ownership and architecture |
| 24 | Portfolio site (Next.js, free hosting): projects with architecture diagrams, eval results, cost numbers, short demo videos |
| 26 | Three written project deep-dives (blog-style, in the repos or on the site) that double as interview scripts |
| 28-34 | Interview prep cycles (below) |
| 34 | Final resume and target list of roles and companies |
| 36 | Start applying, or earlier if an opportunity appears |

## Interview preparation

**System design for LLM apps** (practise out loud with the `mentor` and `architect` agents): design a document Q&A product; design an agent that acts in a third-party system safely; design a chat feature for an existing SaaS with cost limits; design an eval pipeline; design for a model swap without regressions.

**Project explanations**: a two-minute and a ten-minute version for each project, covering problem, architecture, hardest decision, what went wrong, numbers.

**Concept questions**: every `notes/concepts/*.md` ends with interview questions. Review them by phase.

**Coding**: Python fluency exercises (data processing, async HTTP, Pydantic), plus your existing TypeScript strength. Expect take-homes shaped like "build a small RAG or agent over this data"; Changelog Forge and DocPilot make these fast.

**Behavioural**: stories about product decisions, cross-functional UX work, ownership, mentoring; and the AI transition story itself (why, how, evidence).

## GitHub profile baseline (audited 2026-09-05, public data only)

**State.** 31 public repos, all TypeScript/JavaScript, zero Python. Six pinned repos are 2023 tutorial clones. Last public push was November 2024; zero contributions in 2025 and 2026 so far. No profile README. 29 of 31 repos have no description and none have topics. About 20 READMEs are framework boilerplate. Three repos touch AI, all tutorial-derived on the deprecated `openai` v3 Node SDK (chat proxy, DALL-E proxy, a voice SDK demo). No tests, CI, Dockerfiles, `.env.example`, licenses, or architecture docs anywhere. Positives: breadth across web, mobile, and backend; eight deployed demos (2023-2024, not re-verified); one well-documented README (FullStack-GoogleDoc).

**How it reads today.** A 2023 bootcamp-style learner portfolio that went quiet, not a senior engineer's. The roadmap fixes this by construction: every project is original, Python-inclusive, tested, deployed, and documented, and weekly commits restore the activity graph.

**Housekeeping tasks (Phase 0-1, low effort, high signal)**
- [ ] Create the profile README (`saad-official/saad-official`): current role in one line, what you are building, links to the journey repo and, later, the four flagship projects.
- [ ] Add a one-line description and 3-5 topics to every repo you keep.
- [ ] Review the `temp` repo (README titled "Zts Android"): if it is a work or test stub pushed by accident, delete it or make it private. Check it does not contain anything proprietary.
- [ ] Archive (do not delete) the practice repos: `schema-app`, `Portfolio-Practice`, `Typescript-Challenge`, `clipborad-website`, `Ecommerce-Webiste-Nodejs`, and rename obvious clones with a `learning-` prefix or archive them so they stop diluting the list.
- [ ] Re-check the eight demo URLs; remove dead links from READMEs.
- [ ] Update bio: role, focus ("Full-stack engineer building AI-powered products"), location if you want it, link to the portfolio site once it exists.
- [ ] Replace pinned repos progressively: journey repo now; Changelog Forge after Phase 1; DocPilot RN after Phase 2; Review Radar after Phase 3.
- [ ] Add a license, `.env.example`, tests, and a CI badge to every new repo from day one.
- [ ] Make a few small upstream contributions (docs fixes to an SDK you use) during Phases 2-3; they signal open-source literacy.

## Job-market notes

Filled in by the `researcher` agent at week 20 with current postings: most common titles, top skills requested, salary bands in target markets, remote-friendliness, and companies hiring for full-stack + AI. Initial research from September 2026 is summarised in `TECHNOLOGY_STACK.md` under "Industry relevance".
