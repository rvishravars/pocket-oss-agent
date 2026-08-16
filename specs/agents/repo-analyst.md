---
agent: repo-analyst
position: 4
consumes: [repo_facts]
produces: repo_intelligence
tooling: GitHub REST API via httpx, Claude structured output
status: implemented
---

# Repo Analyst

Produces a deep, LLM-synthesized understanding of a repository - architecture,
tech stack, contribution culture, and a per-issue read of what each
beginner-friendly issue actually requires.

Runs **offline, once per repository**, not once per user session.
`repo_facts` from `github-repo-investigator` is a token-budgeted fact sheet:
titles, labels, counts - no issue bodies, no comment threads, no README text.
This agent is where that raw material actually gets read.

## Why this exists

`env-setup-validator`, `repo-vibe-checker` and `skill-matcher` all reason from
`repo_facts` alone: label-based filtering, merge-rate arithmetic, title-only
embedding similarity. None of it reads what an issue actually says, so a
"first mile setup" or a "your first contribution" pick reflects surface
metadata, not a real read of the repository. This agent supplies the piece
those three could not: a human-quality understanding of the repo, computed
once and reused by every subsequent request for it, rather than recomputed
per user.

## Inputs

| Key | Source | Required |
|-----|--------|----------|
| `repo_facts` | `github-repo-investigator` | Yes |

## Prerequisites

- `GITHUB_TOKEN` is present in the environment.
- `ANTHROPIC_API_KEY` is present in the environment.

Abort with a descriptive error if `repo_facts` is missing.

## Output

Writes `repo_intelligence` to the session state object, and separately
persists it behind `RepoIntelligenceStore`, keyed by `owner/repo`, so a second
request for the same repository is a cache read rather than a recomputation.

```json
{
  "repo_slug": "langchain-ai/langchain",
  "architecture_summary": "A framework for building LLM-powered applications, composed of a core abstraction layer (langchain-core) and provider-specific integration packages...",
  "tech_stack": ["Python", "Pydantic", "asyncio"],
  "contribution_culture": "Maintainers respond quickly and give specific implementation guidance rather than closing issues outright.",
  "issues": [
    {
      "issue_id": 32120,
      "difficulty": "moderate",
      "skills": ["Python", "Pydantic", "structured output"],
      "summary": "Add a reasoning-model code path to with_structured_output that tolerates the model's extra reasoning tokens before the JSON payload.",
      "stale_or_claimed": false
    }
  ],
  "model_id": "claude-sonnet-5",
  "computed_at": "2026-08-16T12:00:00Z"
}
```

## Steps

1. **Check the cache first.**
   `RepoIntelligenceStore.get(repo_slug)` before any GitHub or LLM call. A hit
   returns immediately: the entire point of running this offline is that a
   popular repository's analysis is paid for once, not once per contributor
   who asks about it.

2. **Gather raw material** (concurrent GitHub calls, gated on `root_files`
   from `repo_facts` so a missing file costs nothing):
   - `README.md` (and common casing variants), `CONTRIBUTING.md`.
   - For each of `repo_facts.good_first_issues` (already capped at 10 by the
     investigator): the issue body and its comments.

   None of this is summarized before the LLM call - unlike `repo_facts`,
   `RepoIntelligence` is not part of the per-request token budget, since it is
   computed once and the LLM call itself is the summarization step.

3. **Synthesize** with one structured-output call to Claude (Sonnet - this
   step needs judgment across the whole gathered material, not single-field
   extraction, so this is not the tier Haiku is for):
   - An architecture summary and tech stack, from the README and the file
     tree already in `repo_facts`.
   - A contribution-culture read from actual comment tone and maintainer
     behavior on the sampled issues, not from merge-rate arithmetic.
   - Per issue: a difficulty estimate, the skills it actually requires, a
     one-sentence read of what concretely needs to happen, and whether it
     looks stale or already claimed - all from the body and comments, not
     the title or labels alone.

4. **Persist** the result via `RepoIntelligenceStore.put`, then return it.

## Verify

- `repo_intelligence.issues` covers every id in `repo_facts.good_first_issues`
  - a partial result is worse than an honest failure, since a consumer has no
    way to tell "not analyzed" from "analyzed, nothing notable."
- A cache hit makes no GitHub or Claude call. This is the property that makes
  running this per-repository rather than per-request worth doing at all, so
  it is asserted directly rather than inferred from output shape.

## Downstream

Wired into the live graph as of 2026-08-16, between `github-repo-investigator`
and the `validate_setup`/`check_vibe`/`match_issues` fan-out. Both consumers
treat `repo_intelligence` as a nullable enrichment, never a required input, so
a cache miss that fails - no key configured, a Claude error - degrades to
exactly the behavior before this agent existed rather than aborting the run:

- **`skill-matcher`** drops any candidate `repo_intelligence` read as
  `stale_or_claimed` before ranking, and replaces the generic
  interview-intent sentence in `TopMatch.rationale` with `repo-analyst`'s own
  per-issue summary when one covers the winning issue. The embedding-based
  ranking and its calibrated thresholds (`specs/agents/skill-matcher.md`) are
  unchanged - `repo_intelligence` filters and explains, it does not rescore.
- **`contribution-strategy-generator`** shows `architecture_summary` in the
  Architecture Snapshot section and `contribution_culture` in the Vibe Check
  section, and excludes stale issues from the browse-manually fallback list
  the same way `skill-matcher` excludes them from ranking.

## References

- `specs/agents/github-repo-investigator.md` - step 2 of that spec named this
  exact gap (`readme_summary`/`contributing_summary` staying null) before this
  agent existed to fill it.
