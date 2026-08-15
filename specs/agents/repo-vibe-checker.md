---
agent: repo-vibe-checker
position: 5
consumes: [repo_facts]
produces: vibe_summary
tooling: GitHub REST and search APIs via httpx
status: implemented
---

# Repo Vibe Checker

Scores contributor-friendliness and maintainer responsiveness.
Populates the "Vibe Check" section of the roadmap.
Runs after `github-repo-investigator`, in parallel with `env-setup-validator`.

## Inputs

| Key | Source | Required |
|-----|--------|----------|
| `repo_facts.owner`, `repo_facts.repo` | `github-repo-investigator` | Yes |

Abort with a descriptive error if `repo_facts` is absent.

## Output

Writes `vibe_summary` to the session state object.

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

## Steps

1. **Commit recency**
   - Fetch the last 10 commits on the default branch.
   - Compute days since the most recent.

     | Days | Status |
     |------|--------|
     | 0 to 7 | 🟢 Actively maintained |
     | 8 to 30 | 🟡 Moderate activity |
     | 31 to 90 | 🟠 Slowing down |
     | over 90 | 🔴 Potentially dormant |

2. **Issue response time**
   - Fetch the last 20 issues carrying at least one comment.
   - Average the gap between `created_at` and the first maintainer comment.
   - Count only comments from users with write access, identified by an
     `author_association` of `OWNER`, `MEMBER` or `COLLABORATOR`.
     Contributor replies to each other are not maintainer responsiveness.
   - An issue that never drew a maintainer reply is excluded from the average
     rather than counted as an instant response.
   - Comments are not included in the issues listing, so each sampled issue
     costs one request. The sample is capped at 20 and issued concurrently.

     | Days | Status |
     |------|--------|
     | under 2 | 🟢 Very responsive |
     | 2 to 7 | 🟡 Moderate |
     | over 7 | 🔴 Slow to respond |

3. **PR merge rate**
   - Compare merged PRs against total closed PRs over the last 90 days.
   - Use the **search API** for exact totals, one query for `is:merged` and one
     for `is:closed`, both bounded by `closed:>=`.
     The listing endpoint cannot sort by close date, so paging it yields a
     biased sample: psf/requests had 113 PRs closed in the window, of which a
     50-item page sorted by update time saw a subset, reporting 0.27 against a
     true 0.21.
   - Above 0.60 is healthy.
   - Flag above 30 percent closed-without-merge as high rejection risk.
   - Note that healthy projects can sit far below this. pallets/flask merges 3
     of every 50 closed PRs, so the threshold reads more as a warning to a
     newcomer than as a judgement on the project.

4. **Welcome signals**
   - `CONTRIBUTING.md` present: +1
   - `good-first-issue` label in active use: +1
   - `.github/ISSUE_TEMPLATE/` present: +1
   - `CODE_OF_CONDUCT.md` present: +1
   - The first, third and fourth come from one `community/profile` call rather
     than three content lookups. The second reuses
     `repo_facts.good_first_issues`, already computed upstream.
   - A missing community profile degrades the score. A rate-limited one aborts,
     so throttling is never scored as absence.

     | Score | Rating |
     |-------|--------|
     | 4 | Welcoming |
     | 2 to 3 | Moderate |
     | under 2 | Unfriendly |

5. **Compose the summary**
   - Two to three sentences combining every signal.
   - Example: _"This repo is actively maintained (last commit 2 days ago) and
     maintainers respond to issues within 1 day on average. There are 12 open
     `good-first-issue` tickets and a well-structured CONTRIBUTING.md.
     Overall vibe: 🟢 Highly welcoming."_

6. **Verify**
   - At least 3 of the 4 signal groups resolved.
   - Abort with a clear error if the repository is private or the API is
     rate-limited, rather than reporting a partial score as complete.

## References

- `scripts/vibe_check.py`
- `examples/vibe_output.json`
