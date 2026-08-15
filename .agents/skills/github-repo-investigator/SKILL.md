---
name: github-repo-investigator
description: >-
  Use this skill when the user provides a GitHub repository URL and wants a deep
  analysis of the codebase. Uses the GitHub MCP Server to fetch repo structure,
  documentation, issues, and PR activity without consuming excessive LLM tokens.
---

# GitHub Repo Investigator Skill

Analyzes a GitHub repository to produce a structured fact sheet used by
`contribution-strategy-generator` and `repo-vibe-checker`.

## Prerequisites

- GitHub MCP Server is configured and running (see `mcp_config.json`).
- A valid public GitHub repository URL is provided.
- GitHub personal access token is set in the environment as `GITHUB_TOKEN`.

## Steps

1. **Parse the Repository URL**
   - Extract `owner` and `repo` from the URL.
   - Example: `https://github.com/langchain-ai/langchain` → `owner=langchain-ai`, `repo=langchain`

2. **Fetch Core Documentation via MCP**
   - Use the GitHub MCP Server to retrieve:
     - `README.md` → Architecture overview
     - `CONTRIBUTING.md` → Contribution guidelines
     - `CODEOWNERS` (if present) → Key maintainers
   - Summarize each file to under 500 tokens before passing downstream.

3. **Map the File Tree**
   - Fetch the top-level directory structure (depth ≤ 2).
   - Identify key directories: `src/`, `lib/`, `tests/`, `docs/`, `examples/`.
   - Record this as the **Architecture Snapshot**.

4. **Triage Open Issues**
   - Query issues with labels: `good-first-issue`, `help-wanted`, `beginner`.
   - Filter for issues opened or commented on in the last 90 days.
   - Return top 10 candidates with: title, URL, label, days open.

5. **Check PR Activity**
   - Fetch the last 20 merged PRs.
   - Calculate average time-to-merge.
   - Flag repos where average > 30 days as "slow-moving."

6. **Verify**
   - Confirm at least 1 `good-first-issue` was found, or log a warning.
   - Validate that the Architecture Snapshot has at least 3 identified directories.

## Output Schema

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
    { "title": "Fix typo in README", "url": "...", "days_open": 3 }
  ],
  "avg_pr_merge_days": 4.2
}
```

## References

- [GitHub MCP Server docs](./references/github_mcp.md)
- [Issue triage script](./scripts/triage_issues.py)
