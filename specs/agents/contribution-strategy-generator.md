---
agent: contribution-strategy-generator
position: 7
consumes: [developer_context, interview_context, repo_facts, setup_steps, vibe_summary, top_match]
produces: roadmap
tooling: LLM
---

# Contribution Strategy Generator

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

Abort with a descriptive error naming the missing key if any required input is
absent.
`top_match` is the one permitted null, and only when `skill-matcher` reported
no issue above its 0.4 threshold.
In that case render the browse-manually fallback in place of the Target
section rather than omitting the section.

## Output

Writes `roadmap` to the session state object as a Markdown string, at most 60
lines, ready for the UI to render.

## Steps

1. **Load and validate**
   - Read all six inputs from session state.
   - Validate before generating.
     A partial roadmap that silently drops a section is worse than an error,
     because the user cannot tell what is missing.

2. **Architecture Snapshot**
   - 3 to 5 bullets from `repo_facts.architecture_snapshot`.
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
   - Issue title, URL, and rationale from `top_match`.
     ```
     ## 🎯 Your First Contribution
     **Issue:** [Add support for async Python client](#1234)
     **Why you:** You have 5 years of Python experience with asyncio.
     ```

5. **Vibe Check**
   - `vibe_summary` plus its supporting metrics.
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
