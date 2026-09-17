# AI Concepts: Knowledge Base Index

One Markdown file per concept in `notes/concepts/`, written when the concept is understood (not before), using the template below. This index lists what exists and what is planned. `[F]` durable fundamental, `[T]` tool-specific. Checkbox: `[ ]` not started, `[~]` note drafted, `[x]` understood and applied.

## Template (`notes/concepts/<kebab-name>.md`)

```markdown
# <Concept>

**Status:** draft | learning | understood | applied in project | interview-ready
**Phase:** N   **Tags:** [F]/[T], area

## Concept
What is it, in two or three plain sentences.

## Problem
Why does it exist? What breaks without it?

## Mental model
How to think about it. Analogy to web/mobile engineering if one fits.

## Architecture
Where it sits in a real system. Text data-flow diagram.

## Example
Smallest practical example (code or walkthrough).

## Implementation
What we built with it (lab / project link) and the key code decisions.

## Trade-offs
When to use it, when not to, alternatives.

## Production considerations
Cost, latency, reliability, security, observability, scaling.

## Interview questions
3-6 questions an interviewer could ask, with short model answers.

## Project application
Which project demonstrates this and where in the code.

## References
Links checked, with dates.
```

## Index

### Phase 1: LLM fundamentals and Python
- [x] [tokens-and-context-windows](notes/concepts/tokens-and-context-windows.md) `[F]` — understood; measured in exp-002 (`labs/02-tokens`)
- [ ] prompting-and-message-roles `[F]`
- [~] [generation-parameters](notes/concepts/generation-parameters.md) `[F]` — note drafted (status `learning`); awaiting exp-003 numbers from `labs/03-params`
- [ ] structured-outputs `[F]`
- [ ] tool-calling `[F]`
- [ ] streaming `[F]`
- [ ] hallucination-and-grounding `[F]`
- [ ] provider-abstraction `[F]`
- [ ] cost-and-latency-basics `[F]`
- [ ] prompt-versioning `[F]`
- [ ] modern-python-toolchain `[T]` (uv, ruff, pytest, pyproject)
- [ ] async-python-for-io `[F]`
- [ ] pydantic-at-boundaries `[F]`
- [ ] fastapi-essentials `[T]`

### Phase 2: Retrieval
- [ ] embeddings `[F]`
- [ ] similarity-search `[F]`
- [ ] chunking-strategies `[F]`
- [ ] vector-databases-and-pgvector `[F]/[T]`
- [ ] hybrid-search-and-rrf `[F]`
- [ ] reranking `[F]`
- [ ] rag-pipeline `[F]`
- [ ] rag-evaluation `[F]`
- [ ] query-transformations `[F]`
- [ ] citations-and-grounding `[F]`
- [ ] when-not-to-use-rag `[F]`
- [ ] document-parsing `[T]`

### Phase 3: Agents
- [ ] agent-loop `[F]`
- [ ] tool-design `[F]`
- [ ] planning-vs-workflows `[F]`
- [ ] agent-memory `[F]`
- [ ] human-in-the-loop `[F]`
- [ ] durable-execution-and-checkpoints `[F]`
- [ ] mcp `[T]` (concept `[F]`: standardised tool servers)
- [ ] multi-agent-patterns `[F]`
- [ ] agent-evaluation `[F]`
- [ ] agent-security `[F]`
- [ ] langgraph-and-pydantic-ai `[T]`

### Phase 4: Production
- [ ] multi-tenancy-and-authz `[F]`
- [ ] caching-for-llm-apps `[F]`
- [ ] model-routing-and-fallbacks `[F]`
- [ ] llm-observability `[F]/[T]`
- [ ] prompt-and-model-versioning `[F]`
- [ ] evals-in-ci `[F]`
- [ ] prompt-injection-defence `[F]`
- [ ] pii-and-privacy `[F]`
- [ ] rate-limits-and-budgets `[F]`
- [ ] deployment-architecture `[F]/[T]`
- [ ] background-jobs-and-queues `[F]`

### Phase 5: Product
- [ ] unit-economics-of-llm-features `[F]`
- [ ] ai-ux-patterns `[F]` (streaming, uncertainty, citations, approvals, latency masking)
- [ ] multimodal-basics `[F]` (if the chosen product needs images/audio)

### Local inference
- [ ] local-models-and-quantization `[F]/[T]`
- [ ] local-embeddings `[T]`
