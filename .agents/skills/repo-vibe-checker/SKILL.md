---
name: repo-vibe-checker
description: >-
  Use this skill when the user wants to assess the health and contributor-friendliness
  of a GitHub repository. Checks maintainer responsiveness, commit recency, and PR
  merge rates to produce a "Vibe Check" sentiment summary for new contributors.
---

# Repo Vibe Checker Skill

Produces a contributor sentiment report for a GitHub repository. The output
populates the "Vibe Check" section of the final 1-page roadmap.

## Prerequisites

- GitHub MCP Server is configured and accessible.
- Repository `owner` and `repo` are known (from `github-repo-investigator`).

## Steps

1. **Check Commit Recency**
   - Fetch the last 10 commits on the default branch.
   - Calculate days since the most recent commit.
   - Flag thresholds:
     - ≤ 7 days → 🟢 **Actively maintained**
     - 8–30 days → 🟡 **Moderate activity**
     - 31–90 days → 🟠 **Slowing down**
     - > 90 days → 🔴 **Potentially dormant**

2. **Measure Issue Response Time**
   - Fetch the last 20 issues that have at least one comment.
   - Calculate average time between `created_at` and the first maintainer comment.
   - Thresholds:
     - < 2 days → 🟢 **Very responsive**
     - 2–7 days → 🟡 **Moderate**
     - > 7 days → 🔴 **Slow to respond**

3. **Measure PR Merge Rate**
   - Count: merged PRs vs. total closed PRs in the last 90 days.
   - A merge rate > 60% is healthy.
   - Flag repos where > 30% of PRs are closed-without-merge as "high rejection risk."

4. **Check for New Contributor Welcome Signals**
   - Presence of `CONTRIBUTING.md` → ✅ +1
   - Presence of `good-first-issue` label in active issues → ✅ +1
   - Presence of `.github/ISSUE_TEMPLATE/` → ✅ +1
   - Presence of `CODE_OF_CONDUCT.md` → ✅ +1
   - Score: 4/4 = "Welcoming", 2–3/4 = "Moderate", < 2/4 = "Unfriendly"

5. **Compose Vibe Check Summary**
   - Combine all signals into a 2–3 sentence natural language summary.
   - Example: _"This repo is actively maintained (last commit 2 days ago) and maintainers
     respond to issues within 1 day on average. There are 12 open `good-first-issue` tickets
     and a well-structured CONTRIBUTING.md. Overall vibe: 🟢 Highly welcoming."_

6. **Verify**
   - Ensure at least 3 of the 4 signals were resolvable via GitHub API.
   - If the repo is private or API rate-limited, surface an error with a clear message.

## Output Schema

```json
{
  "commit_recency_days": 2,
  "commit_status": "actively_maintained",
  "avg_issue_response_days": 1.3,
  "response_status": "very_responsive",
  "pr_merge_rate": 0.78,
  "welcome_score": 4,
  "welcome_rating": "welcoming",
  "vibe_summary": "This repo is actively maintained..."
}
```

## References

- [Vibe check script](./scripts/vibe_check.py)
- [Example vibe output](./examples/vibe_output.json)
