---
agent: contribution-strategy-generator
position: 8
consumes: [developer_context, interview_context, repo_facts, setup_steps, vibe_summary, top_match, repo_intelligence]
produces: roadmap
tooling: deterministic templating; no LLM call
status: implemented
---

# Contribution Strategy Generator

Implemented as deterministic templating rather than an LLM call.
Every sentence is composed from structured upstream fields, which keeps the
output reproducible, keeps the line budget enforceable, and removes any chance
of the terminal step inventing a fact no agent established.

The Weaver.
Synthesizes every upstream output into the final one-page roadmap.
Terminal node of the pipeline.

## Inputs

| Key | Source | Required |
|-----|--------|----------|
| `developer_context` | `resume-parser` | Yes |
| `interview_context` | `interviewer-agent` | Yes |
| `repo_facts` | `github-repo-investigator` | Yes |
| `setup_steps` | `env-setup-validator` | Yes |
| `vibe_summary` | `repo-vibe-checker` | Yes |
| `top_match` | `skill-matcher` | Nullable |
| `repo_intelligence` | `repo-analyst` | Nullable |

Abort with a descriptive error naming the missing key if any required input is
absent.
`top_match` is nullable when `skill-matcher` reported no issue above
`MINIMUM_SCORE`; in that case render the browse-manually fallback in place of
the Target section rather than omitting the section.
`repo_intelligence` is nullable for a different reason: it is a cache-backed
enrichment from `repo-analyst` that may not have been computed yet for this
repository, so its absence only reduces how much a section says, never
whether the roadmap can render.

## Output

Writes `roadmap` to the session state object as a Markdown string, at most 60
lines, ready for the UI to render.

## Steps

1. **Load and validate**
   - Read all seven inputs from session state.
   - Validate before generating.
     A partial roadmap that silently drops a section is worse than an error,
     because the user cannot tell what is missing.

2. **Architecture Snapshot**
   - 3 to 5 bullets from `repo_facts.architecture_snapshot`.
   - When `repo_intelligence.architecture_summary` is available, show it as a
     lead sentence above the bullets - real prose from having actually read
     the README, not just the detected top-level directories.
     ```
     ## 🗺️ Architecture Snapshot
     - `src/` - Core library logic
     - `tests/` - Unit and integration tests
     - `docs/` - Documentation (MkDocs)
     ```

3. **First Mile Setup**
   - Numbered commands from `setup_steps`, each marked ✅ `validated` or
     ⚠️ `unverified`.
     Never upgrade an `unverified` step to ✅.
     ```
     ## 🚀 First Mile Setup
     1. `git clone https://github.com/owner/repo`
     2. `poetry install` ✅
     3. `docker-compose up -d` ✅
     4. `poetry run pytest` ✅
     ```

4. **Your First Contribution**
   - Issue title, URL, and rationale from `top_match`. When `top_match` is
     null, list up to `MAX_FALLBACK_ISSUES` from `repo_facts.good_first_issues`
     - excluding any `repo_intelligence` read as `stale_or_claimed`, the same
     exclusion `skill-matcher` applies before ranking. If every candidate was
     excluded that way, say so explicitly rather than implying the repo has
     no beginner-friendly issues at all.
     ```
     ## 🎯 Your First Contribution
     **Issue:** [Add support for async Python client](#1234)
     **Why you:** You have 5 years of Python experience with asyncio.
     ```

5. **Vibe Check**
   - `vibe_summary` plus its supporting metrics.
   - When `repo_intelligence.contribution_culture` is available, add it as a
     second, italicized line - `repo-analyst`'s own read of actual comment
     tone, a different kind of signal from the quantitative merge-rate and
     response-time numbers above it, so it is set off rather than blended in.
     ```
     ## 💬 Vibe Check
     🟢 Highly welcoming - last commit 2 days ago, issues answered in ~1 day.
     Maintainer merge rate: 78%. CONTRIBUTING.md and CoC present.
     ```

6. **Assemble**
   - Header:
     ```markdown
     # OSS Contribution Roadmap: {repo_name}
     > Generated for {developer_name} · {seniority} {domain} engineer
     > 🎯 Goal: {interview_context.goal} · ⏱️ Availability: {interview_context.time_commitment}
     ```
   - Adapt tone from `interview_context`:

     | Signal | Adaptation |
     |--------|-----------|
     | `goal:learning` | Add a "What you'll learn" callout to the Target section |
     | `goal:career` | Add a "How this helps your job search" callout |
     | `time:light` | Prefix each setup step with an estimate, such as `~2 min` |
     | `risk:low` | Open the Target section with a reassurance line |

   - Enforce the 60-line ceiling.
   - Truncate an over-budget section with `…` and a link to full details.
     Never drop a section to fit.

7. **Verify**
   - All four sections present.
   - Total line count at most 60.
   - Every issue URL is a non-empty string beginning with `https://`.
   - The header carries both `goal` and `time_commitment`.
   - At least one tone adaptation from step 6 was applied.

## References

- `resources/roadmap_template.md`
- `examples/sample_roadmap.md`
