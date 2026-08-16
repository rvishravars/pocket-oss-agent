# Agent Specifications

Specifications for the eight production agents in the Pocket OSS Agent pipeline.
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
| 4 | `repo-analyst` | `repo_facts` | `repo_intelligence` |
| 5 | `env-setup-validator` | `repo_facts` | `setup_steps` |
| 6 | `repo-vibe-checker` | `repo_facts` | `vibe_summary` |
| 7 | `skill-matcher` | `developer_context`, `interview_context`, `repo_facts`, `repo_intelligence` (optional) | `top_match` |
| 8 | `contribution-strategy-generator` | all of the above, `repo_intelligence` (optional) | `roadmap` |

Steps 1 and 3 run in parallel.
Steps 4, 5 and 6 run in parallel once 3 completes.
The `position` field in each spec's frontmatter matches the numbering above.

`repo-analyst` (4) runs offline and cache-backed - once per repository, not
once per request - but it is still a real node in the live LangGraph pipeline:
`match_issues` and `roadmap` both wait on it, same as any other join. What
makes it different is that its output is optional everywhere it is consumed:
a cache miss that fails degrades to `repo_intelligence: null` rather than
aborting the run, so a request never blocks on it succeeding. See
`specs/agents/repo-analyst.md`'s Downstream section for exactly what each
consumer does with it.

## Conventions

Every spec carries frontmatter naming its session-state contract:

```yaml
agent: skill-matcher
position: 7
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
- **A threshold written before the measurement is a guess.**
  Both numeric thresholds in this system were wrong when first measured: the
  0.60 merge rate flags healthy projects as risky, and the 0.40 similarity floor
  is roughly twice too high, so the matcher never fires. Cosine similarity and
  merge rates are scale-dependent on the model or corpus behind them. Keep every
  threshold in a named constant, measure it against real data before trusting
  it, and record the measurement next to the number.
- **Ordering can be right while the threshold is wrong.**
  The matcher ranks relevant issues above irrelevant ones cleanly and still
  returns nothing, because the cutoff sits above the whole range. Check the
  ranking and the cutoff separately; a correct ranking says nothing about
  whether the gate is calibrated.
- **Pick the cheapest model tier that supports the feature.**
  Where a step is single-shot and its inputs fully determine its output, there
  is no reasoning or tool use to lose by dropping a tier. Resume extraction runs
  on Haiku at roughly a fifth of Opus cost. Keep the model a constructor
  argument so a route needing more can pass one.
- **Everything in a schema is sent to the model.**
  A Pydantic model's class docstring becomes the schema description on every
  call. Write it for the model; implementation rationale belongs in a comment,
  where it costs no tokens.
- **Check `stop_reason` before reading content.**
  A refusal returns HTTP 200 with empty or partial content, so reading the
  parsed output first turns a policy decline into an unrelated attribute error.

## Status

| Agent | State |
|-------|-------|
| `github-repo-investigator` | Implemented except step 2, the LLM summaries - see `repo-analyst` |
| `repo-analyst` | Implemented and wired into the live pipeline |
| `repo-vibe-checker` | Implemented |
| `env-setup-validator` | Implemented except step 5, the sandboxed dry run |
| `interviewer-agent` | Implemented |
| `contribution-strategy-generator` | Implemented |
| `resume-parser` | Implemented; verified against the live Claude API |
| `skill-matcher` | Implemented; thresholds calibrated against real repos |

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
