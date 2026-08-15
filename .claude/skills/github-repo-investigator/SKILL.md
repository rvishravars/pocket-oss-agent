---
name: github-repo-investigator
description: >-
  Use this skill when the user provides a GitHub repository URL and wants a
  deep analysis of the codebase. Uses the `gh` CLI to fetch repo structure,
  documentation, issues, and PR activity, summarizing before passing results
  downstream to keep token usage low.
---

# GitHub Repo Investigator Skill

Analyzes a public GitHub repository to produce a structured fact sheet used
by `contribution-strategy-generator`, `repo-vibe-checker`,
`env-setup-validator`, and `skill-matcher`.

## Prerequisites

- `gh` CLI is installed and authenticated (`gh auth status`). If not
  authenticated, tell the user to run `gh auth login` first — don't attempt
  to fetch private-repo data unauthenticated.
- A valid public GitHub repository URL is provided.

## Steps

1. **Parse the Repository URL**
   - Extract `owner` and `repo` from the URL.
   - Example: `https://github.com/langchain-ai/langchain` → `owner=langchain-ai`, `repo=langchain`

2. **Fetch Core Documentation**
   - Retrieve `README.md`, `CONTRIBUTING.md`, and `CODEOWNERS` (if present):
     ```bash
     gh api repos/{owner}/{repo}/readme --jq .content | base64 -d
     gh api repos/{owner}/{repo}/contents/CONTRIBUTING.md --jq .content | base64 -d
     ```
   - Summarize each file to under 500 tokens before carrying it forward —
     don't keep full raw text in context past this step.

3. **Map the File Tree**
   - Fetch the top-level directory structure (depth ≤ 2):
     ```bash
     gh api repos/{owner}/{repo}/git/trees/HEAD?recursive=0
     ```
   - Identify key directories: `src/`, `lib/`, `tests/`, `docs/`, `examples/`.
   - Record this as the **Architecture Snapshot**.

4. **Triage Open Issues**
   - Query issues with beginner-friendly labels, opened or commented on in
     the last 90 days:
     ```bash
     gh issue list --repo {owner}/{repo} --label "good first issue,help wanted,beginner" --state open --limit 30 --json number,title,url,labels,updatedAt,createdAt,comments
     ```
   - Return the top 10 candidates with: title, URL, label, days open.

5. **Check PR Activity**
   - Fetch the last 20 merged PRs and calculate average time-to-merge:
     ```bash
     gh pr list --repo {owner}/{repo} --state merged --limit 20 --json number,createdAt,mergedAt
     ```
   - Flag the repo as "slow-moving" if the average exceeds 30 days.

6. **Verify**
   - Confirm at least 1 good-first-issue-style candidate was found, or note
     the warning explicitly.
   - Validate that the Architecture Snapshot has at least 3 identified
     directories.

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
