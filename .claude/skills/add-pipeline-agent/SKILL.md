---
name: add-pipeline-agent
description: >-
  Development workflow for this codebase when adding a new pipeline agent,
  changing an existing one, or wiring a new external service into it. Covers
  the spec-first order, the injected-protocol seam that keeps the suite
  offline, the fail-loudly contract, and what to verify before believing a
  green suite. Use when writing or modifying code under
  src/pocket_oss_agent/, not when running the product against a repository.
---

# Adding or changing a pipeline agent

This is about writing code in this repository. It does not perform any agent's
job; `specs/agents/` holds the product specifications and is the contract this
workflow implements against.

## Order of work

1. **Read the spec first.** `specs/agents/<name>.md` is the contract. Its
   frontmatter names what the agent consumes and produces, keyed to the session
   state object in `AGENTS.md`.
2. **Implement against the spec, not around it.** Where the spec is wrong,
   fix the spec in the same change. A spec and its implementation move
   together; a spec that describes something the code does not do is worse
   than no spec.
3. **Verify against real data before believing the suite.** Every significant
   bug in this codebase passed its mocked tests first. Run
   `/run-pipeline <owner/name>` and read the output critically.
4. **Update the status table** in `specs/agents/README.md`.

## The seam

Every external service is injected behind a protocol, never constructed inside
an agent:

| Service | Protocol | Production | Test |
|---------|----------|------------|------|
| LLM | `ProfileExtractor` | `ClaudeProfileExtractor` | a fake in the test module |
| Embeddings | `EmbeddingProvider` | `SentenceTransformerEmbeddings` | `DeterministicEmbeddings` |
| Vectors | `VectorStore` | `PgVectorStore` | `InMemoryVectorStore` |
| GitHub | injected `GitHubClient` | the real client | respx-mocked transport |

This is what lets the suite run with no API key, no model download and no
database, and it is why CI cannot spend money. A new external service gets a
protocol before it gets a caller.

## Contracts to honour

- **Fail loudly.** A missing required input raises `MissingUpstreamOutput`
  naming the agent and the key. No agent substitutes a default. The single
  contractual null is `top_match`, when `skill-matcher` clears nothing.
- **One failure surface.** Map every error onto a `PipelineError` subclass.
  A raw transport exception escaping to the caller is a bug.
- **An unmeasurable signal is null, not zero.** No merged PRs is not a 0%
  merge rate; no maintainer reply is not an instant response.
- **Never emit a placeholder where a real value belongs.** Return None and let
  the consumer say what is missing.
- **Thresholds go in named constants** and are measured before they are
  trusted. See the `calibrate-threshold` skill.

## Before opening a PR

```bash
ruff format --check . && ruff check .
pytest -q --cov          # gated at 100% of statements and branches
```

Prefer deleting a dead branch over writing a contrived test to cover it. If a
change touches agent behaviour, `/run-pipeline` against a repository unlike the
last one: a monorepo, a dormant project, one with no beginner labels. The
defects show up at the edges.

Tests that call a paid API carry the `live` marker and are deselected by
default everywhere. Never add one to the default suite, and never propose an
API key as a CI secret.
