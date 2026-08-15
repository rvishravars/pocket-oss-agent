# Investigate GitHub Repository

Perform a deep analysis of a GitHub repository using the GitHub MCP Server.

## Usage
Provide the full GitHub repository URL: $ARGUMENTS

## Steps

1. Parse `$ARGUMENTS` to extract `owner` and `repo`.
   If no URL is given, ask the user for it.

2. Using the GitHub MCP Server (or GitHub API), fetch:
   - `README.md` → summarise to ≤ 300 words
   - `CONTRIBUTING.md` → summarise to ≤ 200 words
   - Top-level file tree (depth ≤ 2) → identify `src/`, `tests/`, `docs/`, `lib/`, `examples/`

3. Fetch open issues with labels: `good-first-issue`, `help-wanted`, `beginner`.
   Filter to issues active in the last 90 days. Return top 10 with:
   `{ id, title, url, labels, days_open, comment_count }`

4. Fetch last 20 merged PRs. Calculate average time-to-merge in days.

5. Assemble and store as `repo_facts`:

```json
{
  "owner": "...",
  "repo": "...",
  "readme_summary": "...",
  "contributing_summary": "...",
  "architecture_snapshot": { "src": "...", "tests": "..." },
  "good_first_issues": [ { "id": 0, "title": "...", "url": "...", "days_open": 0, "comment_count": 0 } ],
  "avg_pr_merge_days": 0.0
}
```

6. Warn if fewer than 3 `good-first-issue` tickets exist.
   Tell the user to run `/skill-matcher` next.
