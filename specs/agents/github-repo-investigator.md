---
agent: github-repo-investigator
position: 3
consumes: [repo_url]
produces: repo_facts
tooling: GitHub MCP Server
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

- GitHub MCP Server is configured and running. See `mcp_config.json`.
- `GITHUB_TOKEN` is present in the environment.

Abort with a descriptive error if the MCP Server is unreachable, the URL is
malformed, or the repository is private or rate-limited.

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

2. **Fetch core documentation via MCP**
   - Retrieve `README.md`, `CONTRIBUTING.md`, and `CODEOWNERS` if present.
   - Summarize each to under 500 tokens before storing.
   - `CODEOWNERS` yields the key maintainer list.

3. **Map the file tree**
   - Fetch the directory structure to a depth of 2.
   - Identify `src/`, `lib/`, `tests/`, `docs/`, `examples/`.
   - Store as `architecture_snapshot`, discarding the raw tree.

4. **Triage open issues**
   - Query labels `good-first-issue`, `help-wanted`, `beginner`.
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
