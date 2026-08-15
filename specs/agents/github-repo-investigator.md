---
agent: github-repo-investigator
position: 3
consumes: [repo_url]
produces: repo_facts
tooling: GitHub REST API via httpx
status: implemented except step 2
---

# GitHub Repo Investigator

Produces a structured fact sheet for the target repository.
Runs in parallel with `resume-parser`.
Feeds `env-setup-validator`, `repo-vibe-checker`, `skill-matcher`, and
`contribution-strategy-generator`.

## Inputs

| Source | Value |
|--------|-------|
| User | Public GitHub repository URL |

## Prerequisites

- `GITHUB_TOKEN` is present in the environment.

Abort with a descriptive error if the URL is malformed, or the repository is
private or rate-limited.

### Why REST rather than the MCP Server

The rest of the stack uses the GitHub MCP Server, which exists so an LLM can
choose tools at runtime.
This node makes a fixed sequence of deterministic calls and does its own
reducing, so the token saving is identical while the code stays directly
testable against recorded responses.
`src/pocket_oss_agent/github_client.py` implements only the endpoints below.

## Output

Writes `repo_facts` to the session state object.

```json
{
  "owner": "langchain-ai",
  "repo": "langchain",
  "readme_summary": "...",
  "contributing_summary": "...",
  "architecture_snapshot": {
    "src": "Core library code",
    "tests": "Unit and integration tests",
    "docs": "Documentation site"
  },
  "root_files": ["Dockerfile", "README.md", "pyproject.toml", "uv.lock"],
  "good_first_issues": [
    { "id": 1234, "title": "Fix typo in README", "url": "...", "labels": ["docs"], "days_open": 3, "comment_count": 2 }
  ],
  "avg_pr_merge_days": 4.2
}
```

## Token Budget

This agent is the main defence against context bloat.
Summarize before writing to session state.
Raw file trees and full issue bodies must never reach the session state object
or any downstream LLM call.

## Steps

1. **Parse the repository URL**
   - Extract `owner` and `repo`.
   - `https://github.com/langchain-ai/langchain` gives `owner=langchain-ai`, `repo=langchain`.

2. **Fetch core documentation**
   - Retrieve `README.md`, `CONTRIBUTING.md`, and `CODEOWNERS` if present.
   - Summarize each to under 500 tokens before storing.
   - `CODEOWNERS` yields the key maintainer list.
   - **Not yet implemented.** This is the only step needing an LLM, so
     `readme_summary` and `contributing_summary` stay null rather than guessed.

3. **Map the file tree**
   - Fetch the root tree only, without `recursive`.
     A recursive fetch returns the entire file listing and is truncated by the
     API on large repositories, for no benefit, since only root entries are read.
   - Identify `src/`, `lib/`, `tests/`, `docs/`, `examples/`.
   - Store as `architecture_snapshot`, discarding the raw tree.
   - Also store the root entry names as `root_files`. `env-setup-validator`
     detects the toolchain from these, so preserving them saves it a second
     tree fetch while staying well inside the token budget.
   - Known limitation: monorepos that nest code under `libs/` or `packages/`
     produce an empty snapshot, because the recognised names are not at root.

4. **Triage open issues**
   - Query labels `good first issue`, `help wanted`, `beginner`.
   - Request each label in a **separate call** and union the results.
     GitHub's `labels` parameter is conjunctive, so a single combined query
     matches only issues carrying every label, which is almost never any issue.
   - Deduplicate by issue number; an issue often carries several triage labels.
   - Drop pull requests. The issues endpoint returns them too.
   - Restrict to issues opened or commented on within 90 days.
   - Keep the top 10 with id, title, URL, labels, days open, and comment count.
   - Comment count is required; `skill-matcher` uses it for the
     `collab:guided` adjustment.

5. **Check PR activity**
   - Fetch the last 20 merged PRs and compute average time-to-merge.
   - Flag repositories averaging over 30 days as slow-moving.

6. **Verify**
   - Warn if no `good-first-issue` candidates were found.
     This is a warning, not an abort: `skill-matcher` can still rank
     `help-wanted` issues.
   - Warn if `architecture_snapshot` resolved fewer than 3 directories.

## References

- `references/github_mcp.md`
- `scripts/triage_issues.py`
