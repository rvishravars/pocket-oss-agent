# Claude Code Project Memory

Shared agent context for this repository lives in `AGENTS.md`, imported below.
Keep project-wide facts in `AGENTS.md` so Antigravity and Claude Code stay in sync.
Claude-only rules belong in this file.

@AGENTS.md

## Authoring Guidelines

- Never use the em dash character (U+2014). Use a plain dash "-" instead.
- When writing commit messages, NEVER auto-add your agent name as co-author.
- Never manually modify CHANGELOG.md files or any files that are marked as auto-generated.
- When writing or substantially editing long Markdown files, put each full sentence on its own line.
  Preserve normal Markdown structure, but avoid wrapping multiple sentences onto one physical line.

## Engineering Guidelines

- When making technical decisions, do not give much weight to development cost.
  Instead, prefer quality, simplicity, robustness, scalability, and long-term maintainability.
- When doing bug fixes, always start with reproducing the bug in an E2E setting as closely aligned with how an end user experiences it.
  This makes sure you find the real problem so your fix will actually solve it.
- When end-to-end testing a product, be picky about the UI you see and be obsessed with pixel perfection.
  If something clearly looks off, even if it is not directly related to what you are doing, try to get it fixed along the way.
- Apply that same high standard to engineering excellence: lint, test failures, and test flakiness.
  If you see one, even if it is not caused by what you are working on right now, still get it fixed.

## Testing and Cost

- Every external service sits behind an injected protocol: `ProfileExtractor`
  for the LLM, `EmbeddingProvider` for vectors, `VectorStore` for persistence,
  `GitHubClient` for the API.
  Tests supply fakes, so the suite needs no API key, no model download and no
  database, and CI cannot spend money.
  A test that reaches the network is a bug in the test, not a reason to set a
  token.
- Tests that call a paid API carry the `live` marker and are deselected by
  default **everywhere**, not only in CI.
  Your shell usually carries the key, so defaulting to off locally matters as
  much as in CI: spending money should be a choice, not something discovered
  afterwards.
  Run them deliberately with `pytest -m live`.
- The pytest step blanks `GITHUB_TOKEN`, `ANTHROPIC_API_KEY` and
  `ANTHROPIC_AUTH_TOKEN` so a test that escapes its fake fails as
  unauthenticated rather than quietly passing against live data.
- Heavy dependencies are optional extras, never required.
  `sentence-transformers` pulls in torch, which is far too heavy to install on
  four Python versions in CI.
- Coverage is gated at 100% of statements and branches.
  When a new branch is uncovered, prefer deleting the dead branch over writing a
  contrived test for it.
- Green here is necessary, not sufficient.
  Every significant bug in this codebase passed its mocked tests first.
  Run `/run-pipeline` against a real repository before trusting a change that
  touches agent behaviour.

## Skills

Two directories, and the distinction is load-bearing.

`specs/agents/` holds the **production** specifications: what the seven runtime
agents must do, and the contract the Python implementation is written against.
Nothing there is a Claude Code skill and nothing there should auto-trigger.

`.claude/skills/` holds **development** skills: conventions for writing code in
this repository. They exist to help build the product, never to perform its work.

| Skill | Covers |
|-------|--------|
| `add-pipeline-agent` | Spec-first order, the injected-protocol seam, fail-loudly contracts, what to verify before trusting a green suite |
| `calibrate-threshold` | Measuring a numeric cutoff against real data, after two in this system shipped wrong |

Rules for anything added to `.claude/skills/`:

- **Never write a skill that performs a pipeline agent's job.**
  The seven runtime agents lived there once, and their triggers matched the
  sentences typed while developing, so they shadowed the real implementation
  during testing and returned plausible hand-written output instead of
  exercising the code.
- **Write the description against development phrasing**, never against product
  phrasing. "when adding an agent to this codebase" is safe; "when the user
  provides a GitHub repository URL" recreates the shadowing.
- **Only once there is code to describe.** A skill for something unbuilt teaches
  Claude to hand-simulate it instead of building it.

`.claude/commands/` holds a conversational prototype of the pipeline plus the
`/run-pipeline` and `/check` development commands.
Slash commands only run when typed explicitly, so they cannot shadow anything.
The agent commands are not reconciled with `specs/agents/` and are not
authoritative.
