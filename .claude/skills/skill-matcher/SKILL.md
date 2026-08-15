---
name: skill-matcher
description: >-
  Use this skill when you need to match a developer's technical profile and
  interview answers against a GitHub repository's open issues to find the
  best-fit contribution opportunity. Ranks candidate issues in-context using
  reasoning over skills, interview intent, and issue content - no vector
  database required.
---

# Skill Matcher Skill

Bridges the developer profile (from `resume-parser`), interview intent (from
`interviewer-agent`), and repo facts (from `github-repo-investigator`) to
pick the single best-fit issue.

This is the in-context version for a single Claude Code session: ranking is
done by direct reasoning over the candidate issues, not by a pgvector
similarity search. (The production app described in `idea.md` uses
Postgres+pgvector for this at scale with a real embedding index - that's a
separate system from this skill and doesn't need to exist for this skill to
work.)

## Prerequisites

- `developer_context` (from `resume-parser`) is available in the
  conversation.
- `interview_context` (from `interviewer-agent`) is available in the
  conversation.
- The list of candidate issues (`good_first_issues`) from
  `github-repo-investigator`'s output is available.

## Steps

1. **Load Inputs**
   - Gather `developer_context`, `interview_context`, and the candidate
     issue list from earlier in the conversation.

2. **Apply Hard Filters from Interview Context**
   - If `interview_context.contribution_types` does not include `"any"`,
     discard issues whose labels don't match at least one preferred type:
     - `type:bugfix` → keep issues labelled `bug`
     - `type:docs` → keep issues labelled `documentation`
     - `type:feature` → keep issues labelled `enhancement` or `feature`
     - `type:tests` → keep issues labelled `tests` or `coverage`
     - `type:refactor` → keep issues labelled `refactor` or `performance`
   - If `interview_context.time_commitment == "light"`, discard issues
     whose title/body implies large scope (large refactors, new subsystems).

3. **Rank the Remaining Candidates**
   - For each remaining issue, read its title and available body text and
     judge fit against `developer_context` (languages, frameworks, domain)
     and `interview_context` (goal, risk tolerance, collaboration style).
   - Assign each issue a fit score from 0-1 based on your own judgment -
     this replaces the cosine-similarity step in the pgvector version.
     Treat it as a considered estimate, not a precise measurement.
   - Apply the same adjustments the production scoring model uses, as
     qualitative nudges to your ranking rather than literal arithmetic:
     - Favor issues mentioning the developer's top languages/frameworks.
     - Favor issues matching `interview_context.contribution_types`.
     - If `risk_tolerance == "low"`, deprioritize issues that look
       high-complexity (large diff surface, marked `hard` /
       `high-complexity`, touches core/internals).
     - If `collaboration_style == "guided"`, favor issues with active
       discussion (multiple comments) over quiet ones.

4. **Select the Best Match**
   - Take the top-ranked issue as the **Personalized Target**.
   - Build a 2-sentence rationale combining:
     1. Resume signal: `"You have X years of [language] experience."`
     2. Interview signal: `"Matches your goal to [intent_summary excerpt]
        with [time_commitment] availability."`

5. **Verify**
   - If your top match's fit feels weak (loose keyword overlap only, no
     real skill/goal alignment), say so rather than presenting it with
     false confidence: "No strong match found - recommend browsing issues
     manually."

## Output Schema

```json
{
  "top_match": {
    "issue_id": 1234,
    "title": "Add support for async Python client",
    "url": "https://github.com/...",
    "score": 0.87,
    "rationale": "You have 5 years of Python experience with asyncio. Matches your goal to build portfolio with lightweight fixes and ~5 hrs/week availability."
  },
  "filters_applied": ["contribution_types:bugfix,docs", "time:light"],
  "all_matches": [...]
}
```
