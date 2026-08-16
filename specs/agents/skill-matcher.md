---
agent: skill-matcher
position: 7
consumes: [developer_context, interview_context, repo_facts, repo_intelligence]
produces: top_match
tooling: local embeddings + pgvector
status: implemented
---

# Skill Matcher

Selects the single best-fit issue by running a vector similarity search in
pgvector, filtered and re-scored using interview intent.
Runs after `interviewer-agent`, `github-repo-investigator` and `repo-analyst`.

## Inputs

| Key | Source | Required |
|-----|--------|----------|
| `developer_context` | `resume-parser` | Yes |
| `interview_context` | `interviewer-agent` | Yes |
| `repo_facts.good_first_issues` | `github-repo-investigator` | Yes |
| `repo_intelligence` | `repo-analyst` | No - nullable enrichment |

Abort with a descriptive error if any required key is absent. `repo_intelligence`
is cache-backed and may not have been computed yet for this repository; its
absence changes nothing about whether a match can be found, only how it is
explained. See `specs/agents/repo-analyst.md`.

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
   - Read `repo_intelligence` too, if present. It is a nullable, cache-backed
     enrichment from `repo-analyst`, not a required input.

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
   - If filtering empties the candidate set, skip to step 7 and report no
     match rather than silently relaxing the filters.

3. **Drop issues `repo-analyst` read as stale or claimed**
   - When `repo_intelligence` is available, discard any surviving candidate
     whose id appears in `repo_intelligence.issues` with `stale_or_claimed:
     true`. A label or title-similarity signal has no way to know this;
     `repo-analyst` read the actual comment thread.
   - A candidate `repo_intelligence` does not cover is kept, not dropped:
     absence of a read is not evidence the issue is claimed.
   - Record `repo_intelligence:stale_or_claimed` in `filters_applied` when
     this removes anything.
   - When `repo_intelligence` is absent (cache miss, not yet computed for
     this repository), skip this step entirely - ranking proceeds exactly as
     it did before `repo-analyst` existed.

4. **Generate issue embeddings**
   - For each surviving candidate, embed `title + labels`. The spec originally
     said `title + body[:200]`, but `repo_facts` never carries issue bodies:
     the investigator's token budget forbids them. Labels are the available
     stand-in.
   - Use the model named in the prerequisites.
   - These are request-scoped and need not be persisted.

5. **Run the similarity search**
   ```sql
   SELECT issue_id, title, url, 1 - (embedding <=> $developer_embedding) AS score
   FROM candidate_issues
   ORDER BY embedding <=> $developer_embedding
   LIMIT 5;
   ```

6. **Score and rank**
   - Sort by cosine similarity descending, then apply:

     | Condition | Adjustment |
     |-----------|-----------|
     | Issue mentions any of the developer's top 3 languages | +0.10 |
     | Issue type matches `interview_context.contribution_types` | +0.08 |
     | `risk_tolerance` is `low` and issue is labelled `high-complexity` or `hard` | -0.15 |
     | `collaboration_style` is `guided` and `comment_count` is 3 or more | +0.05 |

   - Persist each component in `score_breakdown` so a recommendation can be
     explained and regression-tested.

7. **Select and explain**
   - The highest scoring issue becomes the Personalized Target.
   - Build a two-sentence rationale:
     1. Resume signal: `"You have X years of [language] experience."`
     2. Interview signal: `"Matches your goal to [intent_summary excerpt] with
        [time_commitment] availability."` - unless `repo_intelligence` covers
        this issue, in which case `repo-analyst`'s own one-sentence technical
        summary replaces the interview-signal sentence, since it says what
        concretely needs to happen rather than restating the developer's
        stated goal back to them.

8. **Verify**
   - A top score above `CONFIDENT_SCORE` is a confident match.
   - **Calibrated 2026-08-16 against real repos, superseding an earlier
     single-repo estimate.** The thresholds were originally written before any
     embedding model was chosen; cosine similarity is scale-dependent, so a
     number picked before that choice does not transfer. `MINIMUM_SCORE` and
     `CONFIDENT_SCORE` compare against the **final boosted score**
     (`semantic_similarity` plus the adjustments in step 6), not raw cosine
     similarity, so that is what has to be measured.

     Measured with `sentence-transformers/all-MiniLM-L6-v2`, one fixed
     developer/interview profile (Python/Go backend, portfolio goal,
     bugfix+docs, low risk tolerance, guided collaboration - the same
     stand-in `scripts/run_pipeline.py` uses), against every `good first
     issue`/`help wanted`/`beginner` issue on nine active repos of varying
     domains. Best boosted score per repo:

     | Repo | Best score | Best issue |
     |------|-----------|-----------|
     | microsoft/terminal | 0.3440 | Mica Alt |
     | elastic/elasticsearch | 0.3434 | API to return global state from a snapshot |
     | langchain-ai/langchain | 0.3412 | Reasoning model with structured output |
     | matplotlib/matplotlib | 0.3213 | Add thumbnails for tutorials/gallery where missing |
     | jupyterlab/jupyterlab | 0.2524 | Shortcuts: Option+[0-9] do not work in Terminal |
     | godotengine/godot | 0.1944 | [TRACKER] Unit tests to add or improve |
     | scikit-learn/scikit-learn | 0.1500 | Automatically move y to the same device |
     | apache/superset | 0.1418 | X-Axis Label Interval "All" does not work |
     | pytest-dev/pytest | 0.0630 | Expose FixtureFunctionDefinition as public API |

     35 candidate issues scored in total, spread continuously from 0.344 down
     to -0.037 - no natural gap, so the floor is a judgment call from the
     shape of the curve rather than a boundary the data draws by itself. The
     top four repos are also the four where the winning issue is genuinely on
     topic for this profile (structured-output APIs, a backend snapshot
     endpoint, chart tooling, dev-tool shortcuts); the bottom five are a
     tracking issue, a device-placement bug, a dashboard label bug, and a
     public-API rename - each real, none in this developer's stack.

     `MINIMUM_SCORE = 0.25` sits just under that top cluster: it admits the
     four repos with an on-topic best match and excludes the five that only
     had off-topic beginner issues available, which is the same distinction a
     human skimming the same nine result sets would draw. `CONFIDENT_SCORE =
     0.32` sits at the bottom of that same top cluster, so "confident" means
     "in the top tier actually observed," not a number no repo has ever
     reached - which is what the original 0.65 was.

     Retuning is a one-line change in `skill_matcher.py`. Reproduce this
     measurement (`scripts/run_pipeline.py <repo> --real-embeddings`, or the
     equivalent direct call to `match_issues`) rather than adjusting by feel,
     and widen the repo sample before moving the floor again.
   - When nothing clears `MINIMUM_SCORE`, emit the warning
     `"No strong match found, recommend browsing issues manually."`
     and leave `top_match` null.
     `contribution-strategy-generator` renders the fallback in that case.

## References

- `references/pgvector_setup.md`
- `scripts/generate_embeddings.py`
