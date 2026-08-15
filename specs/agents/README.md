# Agent Specifications

Specifications for the seven production agents in the Pocket OSS Agent pipeline.
These describe what the agents must do; the Python implementation under LangGraph is written against them.

These are **not** Claude Code skills or Antigravity skills.
They are product requirements.
Nothing here should auto-trigger in a coding session.
See the note at the bottom of `AGENTS.md` for why `.claude/skills/` was removed.

## Intended Use

- Output schemas become Pydantic models.
- Step sequences become LangGraph nodes.
- Example outputs become golden-file fixtures for agent evals.

## Provenance and Known Gaps

These files were moved out of `.claude/skills/`, where they had been adapted to run
in-context inside a single Claude Code session.
That adaptation deliberately stripped the production architecture, so **the current
text describes the prototype, not the production design.**
Each file needs a reconciliation pass before it is a trustworthy contract.

Known divergences from the production stack described in `AGENTS.md`:

| Agent | Current text says | Production should say |
|-------|-------------------|-----------------------|
| `resume-parser` | Read tool, `pdftotext`/`pypdf` fallback | PDF extraction pipeline, LLM structuring, pgvector embedding write |
| `interviewer-agent` | `AskUserQuestion` tool | UI chat or form flow |
| `github-repo-investigator` | `gh` CLI | GitHub MCP Server |
| `skill-matcher` | in-context ranking, "no vector database required" | pgvector cosine similarity with the numeric boost model |
| `env-setup-validator` | `gh api`, local clone | GitHub MCP Server, sandboxed dry run |
| `repo-vibe-checker` | `gh` CLI | GitHub MCP Server |
| `contribution-strategy-generator` | mostly architecture-neutral | closest to production already |

Two cross-cutting gaps apply to every file:

- **State handoff.** The text says outputs are carried forward "in the conversation".
  Production passes the session state object defined in `AGENTS.md`.
- **Error handling.** The text degrades gracefully when an upstream output is missing.
  `AGENTS.md` requires failing loudly instead.

The YAML frontmatter is also vestigial.
`description` fields still read "Use this skill when...", which is skill-trigger
phrasing with no meaning in a specification.

## Open Question

`.agents/skills/` holds Antigravity skill definitions covering the same seven agents,
and that text is closer to the production architecture than what is in this directory.
The two sets need to be reconciled into one source of truth, and a decision is needed
on whether Antigravity should keep runtime skills at all, since they carry the same
category problem that `.claude/skills/` did.
