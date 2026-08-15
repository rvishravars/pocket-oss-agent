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

## Rules Earned the Hard Way

Each of these cost a real bug. They apply to every agent, so they live here
rather than being rediscovered one spec at a time.

- **Never emit a placeholder where a real value belongs.**
  `env-setup-validator` returned `"# no test command detected"` as a command,
  and the roadmap rendered it as a numbered shell step with a time estimate
  beside it. Return null and let the consumer say what is missing.
- **An unmeasurable signal is null, not zero.**
  No merged PRs is not a 0% merge rate; no maintainer reply is not an instant
  response; no commits is not dormancy. Each renders as "could not be
  determined", because a fabricated number is indistinguishable from a real one
  once it reaches the roadmap.
- **Never report a step verified without having run it.**
  A green check the user trusts is worse than an honest warning.
- **Prefer exact counts to sampled pages.**
  GitHub listing endpoints cannot sort by close date, so paging them biases any
  rate computed from the result. Use the search API when the total is what
  matters.
- **Verify against real repositories before believing a green suite.**
  Every significant bug in this codebase passed its mocked tests first: the
  conjunctive `labels` parameter, the truncated recursive tree, the biased merge
  rate, the duplicate installers, missing Ruby, and a placeholder rendered as a
  command. Mocks confirm the code does what you assumed; only live data
  challenges the assumption.
- **Map every failure onto the pipeline's own error type.**
  A raw `httpx.ConnectTimeout` once escaped every `PipelineError` handler during
  a concurrent fan-out. One layer, one failure surface.
- **Deterministic assembly beats an LLM call for composition.**
  Where a step only arranges facts other agents established, template it. That
  keeps output reproducible, budgets enforceable, and removes any chance of the
  final step inventing a fact.
- **The pipeline is a data contract, not a call graph.**
  Adding `DeveloperContext.name` for the roadmap header meant `resume-parser`
  had to start extracting it. A field is not real until the agent that produces
  it says so.

## Status

| Agent | State |
|-------|-------|
| `github-repo-investigator` | Implemented except step 2, the LLM summaries |
| `repo-vibe-checker` | Implemented |
| `env-setup-validator` | Implemented except step 5, the sandboxed dry run |
| `interviewer-agent` | Implemented |
| `contribution-strategy-generator` | Implemented |
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
