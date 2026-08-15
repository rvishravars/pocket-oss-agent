# Agent Specifications

Specifications for the seven production agents in the Pocket OSS Agent pipeline.
These describe what the agents must do.
The Python implementation under LangGraph is written against them.

These are **not** Claude Code skills or Antigravity skills.
They are product requirements, and nothing here should auto-trigger in a coding
session.
See the note at the end of `AGENTS.md` for why both skill directories were
removed.

## Pipeline

| # | Agent | Consumes | Produces |
|---|-------|----------|----------|
| 1 | `resume-parser` | resume PDF | `developer_context` |
| 2 | `interviewer-agent` | `developer_context` | `interview_context` |
| 3 | `github-repo-investigator` | repo URL | `repo_facts` |
| 4 | `env-setup-validator` | `repo_facts` | `setup_steps` |
| 5 | `repo-vibe-checker` | `repo_facts` | `vibe_summary` |
| 6 | `skill-matcher` | `developer_context`, `interview_context`, `repo_facts` | `top_match` |
| 7 | `contribution-strategy-generator` | all of the above | `roadmap` |

Steps 1 and 3 run in parallel.
Steps 4 and 5 run in parallel once 3 completes.
The `position` field in each spec's frontmatter matches the numbering above.

## Conventions

Every spec carries frontmatter naming its session-state contract:

```yaml
agent: skill-matcher
position: 6
consumes: [developer_context, interview_context, repo_facts]
produces: top_match
tooling: pgvector
```

- `consumes` and `produces` refer to keys in the session state object defined in
  `AGENTS.md`.
- Missing required inputs abort with a descriptive error naming the key.
  No agent silently substitutes a default.
  The single exception is `top_match`, which `skill-matcher` may legitimately
  return null when no issue clears its 0.4 similarity threshold.

## Intended Use

- Output schemas become Pydantic models.
- Step sequences become LangGraph nodes.
- Example outputs become golden-file fixtures for agent evals.
- Threshold tables become named constants, so tuning them does not require
  editing prose.

## Status

| Agent | State |
|-------|-------|
| `github-repo-investigator` | Implemented except step 2, the LLM summaries |
| `repo-vibe-checker` | Implemented |
| `env-setup-validator` | Implemented except step 5, the sandboxed dry run |
| everything else | Specified only |

Reconciled against the production stack described in `AGENTS.md`: pgvector for
similarity search, and the session state object for handoff between nodes.
Repository access uses the REST API rather than the MCP Server for the
investigator; the reasoning is recorded in that spec.

A spec and its implementation are expected to move together.
When an implementation teaches you something the spec got wrong, such as
GitHub's conjunctive `labels` parameter, fix the spec in the same change.

An earlier revision of these files described an in-context prototype that used
the `gh` CLI and LLM judgment in place of MCP and pgvector.
That prototype survives as the slash commands in `.claude/commands/`, which run
only when invoked explicitly.
Those commands have not been reconciled with these specs and will drift.
Treat this directory as authoritative.
