---
agent: skill-matcher
position: 6
consumes: [developer_context, interview_context, repo_facts]
produces: top_match
tooling: local embeddings + pgvector
status: implemented
---

# Skill Matcher

Selects the single best-fit issue by running a vector similarity search in
pgvector, filtered and re-scored using interview intent.
Runs after `interviewer-agent` and `github-repo-investigator`.

## Inputs

| Key | Source | Required |
|-----|--------|----------|
| `developer_context` | `resume-parser` | Yes |
| `interview_context` | `interviewer-agent` | Yes |
| `repo_facts.good_first_issues` | `github-repo-investigator` | Yes |

Abort with a descriptive error if any is absent.

## Prerequisites

- PostgreSQL with the `pgvector` extension is running.
- The developer embedding is stored in `developer_profiles`.
- Repository documentation embeddings are stored in `repo_embeddings`.
- Every table and every runtime call uses the same embedding model, for
  example `text-embedding-004`.
  Mixing models silently produces meaningless cosine distances, so the model
  identifier is validated at startup rather than assumed.

## Output

Writes `top_match` to the session state object.

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
  "all_matches": []
}
```

## Steps

1. **Load inputs**
   - Read `developer_context`, `interview_context`, and
     `repo_facts.good_first_issues` from session state.

2. **Apply hard filters from interview context**
   - When `contribution_types` does not include `any`, discard issues whose
     labels match none of the preferred types:

     | Tag | Keeps issues labelled |
     |-----|----------------------|
     | `type:bugfix` | `bug` |
     | `type:docs` | `documentation` |
     | `type:feature` | `enhancement`, `feature` |
     | `type:tests` | `tests`, `coverage` |
     | `type:refactor` | `refactor`, `performance` |

   - When `time_commitment` is `light`, discard issues whose effort label
     exceeds 4 hours.
     Most repositories carry no effort labels, so this filter applies only
     where the label exists and must not discard unlabelled issues.
   - The same rule governs type filtering: an issue carrying no recognised type
     label survives. Absent labels mean the repo does not use that vocabulary,
     not that the issue is unsuitable, and dropping them empties most candidate
     sets.
   - Record every filter applied in `filters_applied`.
   - If filtering empties the candidate set, skip to step 6 and report no
     match rather than silently relaxing the filters.

3. **Generate issue embeddings**
   - For each surviving candidate, embed `title + labels`. The spec originally
     said `title + body[:200]`, but `repo_facts` never carries issue bodies:
     the investigator's token budget forbids them. Labels are the available
     stand-in.
   - Use the model named in the prerequisites.
   - These are request-scoped and need not be persisted.

4. **Run the similarity search**
   ```sql
   SELECT issue_id, title, url, 1 - (embedding <=> $developer_embedding) AS score
   FROM candidate_issues
   ORDER BY embedding <=> $developer_embedding
   LIMIT 5;
   ```

5. **Score and rank**
   - Sort by cosine similarity descending, then apply:

     | Condition | Adjustment |
     |-----------|-----------|
     | Issue mentions any of the developer's top 3 languages | +0.10 |
     | Issue type matches `interview_context.contribution_types` | +0.08 |
     | `risk_tolerance` is `low` and issue is labelled `high-complexity` or `hard` | -0.15 |
     | `collaboration_style` is `guided` and `comment_count` is 3 or more | +0.05 |

   - Persist each component in `score_breakdown` so a recommendation can be
     explained and regression-tested.

6. **Select and explain**
   - The highest scoring issue becomes the Personalized Target.
   - Build a two-sentence rationale:
     1. Resume signal: `"You have X years of [language] experience."`
     2. Interview signal: `"Matches your goal to [intent_summary excerpt] with
        [time_commitment] availability."`

7. **Verify**
   - A top score above 0.65 is a confident match.
   - **The 0.40 and 0.65 thresholds are miscalibrated and must be retuned
     before this ships.** They were written before any embedding model was
     chosen, and cosine similarity is scale-dependent, so they do not transfer.

     Measured with `all-MiniLM-L6-v2` against the profile
     `Python, Go, FastAPI, Django, Docker, AWS, backend`:

     | Issue | Similarity |
     |-------|-----------|
     | Add support for an async Python client | 0.358 |
     | Improve Docker Compose setup for local dev | 0.332 |
     | Fix Go module resolution in the build | 0.190 |
     | Update the CSS on the documentation site | 0.083 |
     | Translate the README into Japanese | 0.015 |

     The **ordering is correct** and clearly separates relevant from irrelevant.
     The **absolute floor is roughly twice too high**: the best match on
     langchain-ai/langchain scored 0.3412, so the roadmap fell back to
     browse-manually. As written these thresholds make the product's core
     feature never fire on any repo.

     On this evidence a floor near 0.25 admits the relevant issues and still
     rejects the noise, with "confident" near 0.35. Both live in named constants
     (`MINIMUM_SCORE`, `CONFIDENT_SCORE`) so retuning is a one-line change, and
     the numbers above should be reproduced on a wider sample first.
   - When no issue scores above 0.4, emit the warning
     `"No strong match found, recommend browsing issues manually."`
     and leave `top_match` null.
     `contribution-strategy-generator` renders the fallback in that case.

## References

- `references/pgvector_setup.md`
- `scripts/generate_embeddings.py`
