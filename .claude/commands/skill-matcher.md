# Match Skills to Issues

Semantically match the developer's profile and interview intent to the best open issue.

## Prerequisites
Ensure these are available in session state before running:
- `developer_context` (from `/resume-parser`)
- `interview_context` (from `/interviewer-agent`)
- `repo_facts.good_first_issues` (from `/github-repo-investigator`)

## Steps

1. **Apply hard filters** from `interview_context`:
   - If `contribution_types` ≠ `any`, keep only issues whose labels match:
     `bugfix→bug`, `docs→documentation`, `feature→enhancement`, `tests→tests/coverage`, `refactor→refactor/performance`
   - If `time_commitment == light`, drop issues with `estimated_effort > 4 hours` labels.

2. **Score each remaining issue** against `developer_context`:
   - Base score: semantic similarity between issue title+body and developer skills description.
   - `+0.10` if issue mentions any of the developer's top 3 languages.
   - `+0.08` if issue type matches `interview_context.contribution_types`.
   - `-0.15` if `risk_tolerance == low` and issue has `high-complexity` or `hard` label.
   - `+0.05` if `collaboration_style == guided` and issue has ≥ 3 comments.

3. **Select top match** (highest score). Build a 2-sentence rationale:
   - Sentence 1 (resume): "You have X years of [language] experience."
   - Sentence 2 (interview): "Matches your goal to [intent_summary] with [time_commitment] availability."

4. Store as `top_match`:

```json
{
  "issue_id": 0,
  "title": "...",
  "url": "...",
  "score": 0.0,
  "score_breakdown": { "semantic_similarity": 0.0, "language_boost": 0.0, "interview_type_boost": 0.0, "risk_penalty": 0.0, "collab_boost": 0.0 },
  "rationale": "...",
  "filters_applied": []
}
```

5. Warn if top score < 0.4. Tell user to run `/contribution-strategy-generator` next.
