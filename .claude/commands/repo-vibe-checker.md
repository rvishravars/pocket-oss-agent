# Check Repo Vibe

Assess the health and contributor-friendliness of the target GitHub repository.

## Prerequisites
Requires `repo_facts` in session state (from `/github-repo-investigator`).

## Steps

1. **Commit recency** - days since most recent commit:
   - ≤ 7 days → 🟢 Actively maintained
   - 8–30 days → 🟡 Moderate activity
   - 31–90 days → 🟠 Slowing down
   - > 90 days → 🔴 Potentially dormant

2. **Issue response time** - average days from `created_at` to first maintainer comment (last 20 issues):
   - < 2 days → 🟢 Very responsive
   - 2–7 days → 🟡 Moderate
   - > 7 days → 🔴 Slow

3. **PR merge rate** - merged / total closed PRs in last 90 days:
   - > 60% → healthy
   - < 40% → flag as "high rejection risk"

4. **Welcome signals** (score 1 point each):
   - `CONTRIBUTING.md` exists ✅
   - Active `good-first-issue` issues exist ✅
   - `.github/ISSUE_TEMPLATE/` exists ✅
   - `CODE_OF_CONDUCT.md` exists ✅

   Score → 4/4: "Welcoming" | 2–3/4: "Moderate" | < 2/4: "Unfriendly"

5. **Write a 2–3 sentence natural language summary** combining all signals.
   Example: _"This repo is actively maintained (last commit 2 days ago) and maintainers
   respond within 1 day on average. 12 open good-first-issue tickets and a structured
   CONTRIBUTING.md. Overall: 🟢 Highly welcoming."_

6. Store as `vibe_summary` (the full object + the text summary).
   Tell user to run `/contribution-strategy-generator` next.
