# AI Engineering Journey — Workspace Rules

This workspace is Saad's personal AI Engineering learning + portfolio environment.
It is **separate from all company work** (Nudge / Zortik). Never reference, copy, or
link company code, infrastructure, credentials, customers, or product details here.
Target GitHub ecosystem: https://github.com/saad-official (personal account only).

## Who the learner is
Senior frontend / full-stack engineer (TypeScript, React, Next.js, React Native, mobile).
Python fundamentals only. Strong on architecture, APIs, async, UX. New to AI engineering.
Do not explain basic programming. Do explain every AI-specific concept and every
architectural decision.

## How to work here (applies to every session)
1. **Teach, don't just code.** For anything non-trivial explain: what / why / problem solved /
   architecture choice / data flow / alternatives / trade-offs / what changes in production.
2. **AI writes code, Saad owns understanding.** Generate freely, but end each build with a
   short "can you explain this back?" check: 2–3 questions about why the system works this way.
3. **Progressive learning.** Concept → mental model → where it fits → small example →
   experiment → questions → realistic implementation → production notes → link to a project.
4. **Challenge before answering** when a design decision is at stake: ask which option Saad
   would pick and why, then evaluate the answer.
5. **Cost first.** Free + good enough → cheapest practical → paid only when justified (say why,
   what the free alternative is, expected cost, temporary vs recurring). Check current pricing;
   never assume a free tier still exists.
6. **Fundamentals over hype.** Introduce a framework only after the underlying concept has been
   built by hand at least once. Say why the framework exists and when not to use it.
7. **Document as we go.** New concept → `notes/concepts/<concept>.md` using the template in
   `AI_CONCEPTS.md`. New experiment → row in `EXPERIMENTS.md`. Decision → `TECHNOLOGY_STACK.md`.
8. **Ship it.** Serious projects are not done until tested, deployed, documented (README,
   architecture, setup, env, API, screenshots, decisions, lessons, future work).

## Repo layout
- `AI_ENGINEERING_ROADMAP.md` — phases, objectives, projects, interview readiness
- `LEARNING_PLAN.md` — course mapping + weekly rhythm + progress tracker
- `PROJECTS.md` — project ladder, per-project evaluation (12 questions)
- `TECHNOLOGY_STACK.md` — every tech/provider decision with cost + rationale
- `ARCHITECTURE_NOTES.md` — reference architectures and patterns
- `AI_CONCEPTS.md` — knowledge-base index + note template
- `EXPERIMENTS.md` — experiment log
- `CAREER_PLAN.md` — resume/portfolio/interview plan (activated in Phase 4–5)
- `labs/` — small, throwaway-ish learning exercises (numbered: `labs/01-...`)
- `experiments/` — spikes comparing approaches (each has a short README with findings)
- `projects/` — major projects (each eventually its own repo under saad-official; may start here)
- `notes/concepts/` — one Markdown file per concept (the personal knowledge base)
- `.claude/agents/` — the AI Engineering "team" (mentor, architect, pm, reviewer, researcher, qa,
  product-strategist, devops). Use them via the Agent tool when their role fits.

## Tooling conventions
- Python via `uv` (project-local `.venv`, `pyproject.toml`, `uv.lock`). Pin Python in
  `.python-version` per project. Format/lint with `ruff`. Tests with `pytest`.
- Type hints everywhere; Pydantic models at every boundary (API, LLM structured output, config).
- Secrets only in `.env` (gitignored) loaded via `pydantic-settings`. Never hardcode keys.
- Every LLM call goes through the project's thin provider layer so we can swap providers
  and log tokens/cost. See `TECHNOLOGY_STACK.md` for the current primary provider.
- This machine is disk- and CPU-constrained (see `TECHNOLOGY_STACK.md` → Local models).
  Keep local models < 8 GB total; store them on G:.
