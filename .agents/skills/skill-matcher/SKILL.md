---
name: skill-matcher
description: >-
  Use this skill when you need to semantically match a developer's technical profile
  and interview answers against a GitHub repository's needs. Performs vector similarity
  search using pgvector, augmented by interview context filters, to find the best-fit
  open issues and contribution opportunities.
---

# Skill Matcher Skill

Bridges the developer profile (from `resume-parser`), interview intent (from
`interviewer-agent`), and repo facts (from `github-repo-investigator`) by running
semantic similarity searches in pgvector augmented by hard preference filters.

## Prerequisites

- PostgreSQL with `pgvector` extension is running.
- Developer Context embedding is stored in the `developer_profiles` table.
- Repo documentation embeddings are stored in the `repo_embeddings` table.
- Both tables use the same embedding model (e.g., `text-embedding-004`).
- `interview_context` JSON is available in the current session state (from `interviewer-agent`).

## Steps

1. **Load Inputs**
   - Retrieve the `developer_context` JSON from the current session.
   - Retrieve the `interview_context` JSON from the current session.
   - Retrieve the list of `good_first_issues` from the repo investigator output.

1a. **Apply Hard Filters from Interview Context**
   - If `interview_context.contribution_types` does not include `"any"`, discard all
     issues whose labels don't match at least one of the preferred types:
     - `type:bugfix` → keep issues labelled `bug`
     - `type:docs` → keep issues labelled `documentation`
     - `type:feature` → keep issues labelled `enhancement` or `feature`
     - `type:tests` → keep issues labelled `tests` or `coverage`
     - `type:refactor` → keep issues labelled `refactor` or `performance`
   - If `interview_context.time_commitment == "light"`, discard issues with
     `estimated_effort > 4 hours` (if effort label is present).

2. **Generate Issue Embeddings**
   - For each candidate issue, concatenate: `title + body (first 200 chars)`.
   - Generate an embedding vector using the same model as the resume profile.
   - Store temporarily in memory (no need to persist).

3. **Run Vector Similarity Search**
   - Query pgvector for the top-N matching issues against the developer embedding:
     ```sql
     SELECT issue_id, title, url, 1 - (embedding <=> $developer_embedding) AS score
     FROM candidate_issues
     ORDER BY embedding <=> $developer_embedding
     LIMIT 5;
     ```

4. **Score and Rank**
   - Sort results by cosine similarity score (descending).
   - Apply secondary score adjustments:
     - Boost issues mentioning any of the developer's top 3 languages by **+0.10**.
     - Boost issues matching `interview_context.contribution_types` by **+0.08**.
     - If `interview_context.risk_tolerance == "low"`, penalise issues with
       complexity labels (`high-complexity`, `hard`) by **−0.15**.
     - If `interview_context.collaboration_style == "guided"`, boost issues with
       active comments (≥ 3 comments) by **+0.05**.

5. **Select the Best Match**
   - Take the top-ranked issue as the **Personalized Target**.
   - Build the rationale from two signals:
     1. Resume: `"You have X years of [language] experience."`
     2. Interview: `"Matches your goal to [intent_summary excerpt] with [time_commitment] availability."`
   - Combine into a single 2-sentence rationale.

6. **Verify**
   - Ensure the top-matched issue score is > 0.65 (reasonable similarity).
   - If no issue scores above 0.4, surface a warning: "No strong match found - recommend browsing issues manually."

## Output Schema

```json
{
  "top_match": {
    "issue_id": 1234,
    "title": "Add support for async Python client",
    "url": "https://github.com/...",
    "score": 0.87,
    "score_breakdown": {
      "semantic_similarity": 0.74,
      "language_boost": 0.10,
      "interview_type_boost": 0.08,
      "risk_penalty": 0.0,
      "collab_boost": 0.05
    },
    "rationale": "You have 5 years of Python experience with asyncio. Matches your goal to build portfolio with lightweight fixes and ~5 hrs/week availability."
  },
  "filters_applied": ["contribution_types:bugfix,docs", "time:light"],
  "all_matches": [...]
}
```

## References

- [pgvector setup guide](./references/pgvector_setup.md)
- [Embedding generation script](./scripts/generate_embeddings.py)
