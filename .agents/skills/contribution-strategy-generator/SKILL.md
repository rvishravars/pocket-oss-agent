---
name: contribution-strategy-generator
description: >-
  Use this skill when you need to synthesize a developer's profile and repository
  analysis into a final one-page OSS contribution roadmap. This is the final step
  in the Pocket OSS Agent pipeline — it weaves all upstream outputs into a
  concise, actionable Markdown strategy document.
---

# Contribution Strategy Generator Skill

The "Weaver" agent. Takes all upstream outputs and generates the final
1-page contribution roadmap restricted to a single screen-view.

## Prerequisites

All of the following upstream skill outputs must be available:
- ✅ `resume-parser` → `developer_context`
- ✅ `interviewer-agent` → `interview_context`
- ✅ `github-repo-investigator` → `repo_facts`
- ✅ `skill-matcher` → `top_match` (best-fit issue)
- ✅ `env-setup-validator` → `setup_steps`
- ✅ `repo-vibe-checker` → `vibe_summary`

## Steps

1. **Load All Inputs**
   - Retrieve all upstream outputs from the current session state.
   - Validate that all 6 inputs are present. Abort with a clear error if any is missing.

2. **Generate Architecture Snapshot Section**
   - Use `repo_facts.architecture_snapshot` to produce a 3–5 bullet summary.
   - Format:
     ```
     ## 🗺️ Architecture Snapshot
     - `src/` — Core library logic
     - `tests/` — Unit and integration tests
     - `docs/` — Documentation (MkDocs)
     ```

3. **Generate First Mile Setup Section**
   - Use `setup_steps` to produce a numbered command list.
   - Mark each step with ✅ or ⚠️ based on validation status.
   - Format:
     ```
     ## 🚀 First Mile Setup
     1. `git clone https://github.com/owner/repo`
     2. `poetry install` ✅
     3. `docker-compose up -d` ✅
     4. `poetry run pytest` ✅
     ```

4. **Generate Personalized Target Section**
   - Use `top_match` to highlight the recommended issue.
   - Include: issue title, URL, and the match rationale.
   - Format:
     ```
     ## 🎯 Your First Contribution
     **Issue:** [Add support for async Python client](#1234)
     **Why you:** You have 5 years of Python experience with asyncio.
     ```

5. **Generate Vibe Check Section**
   - Use `vibe_summary` and raw metrics for a sentiment block.
   - Format:
     ```
     ## 💬 Vibe Check
     🟢 Highly welcoming — last commit 2 days ago, issues answered in ~1 day.
     Maintainer merge rate: 78%. CONTRIBUTING.md and CoC present.
     ```

6. **Assemble the Final Document**
   - Combine all 4 sections with a personalized header:
     ```markdown
     # OSS Contribution Roadmap: {repo_name}
     > Generated for {developer_name} · {seniority} {domain} engineer
     > 🎯 Goal: {interview_context.goal} · ⏱️ Availability: {interview_context.time_commitment}

     [Architecture Snapshot]
     [First Mile Setup]
     [Your First Contribution]
     [Vibe Check]
     ```
   - Adapt section tone based on `interview_context`:
     - `goal:learning` → add a "What you'll learn" callout in the Target section.
     - `goal:career` → add a "How this helps your job search" callout.
     - `time:light` → prepend each setup step with estimated time (e.g. `~2 min`).
     - `risk:low` → open the Target section with a reassurance line.
   - Enforce a **single screen-view** constraint: total output ≤ 60 lines.
   - If any section exceeds its budget, truncate with a `…` and a link to full details.

7. **Verify**
   - Final document must contain all 4 sections.
   - Total line count must be ≤ 60.
   - All issue URLs must be valid (non-empty strings starting with `https://`).
   - Confirm the roadmap header includes both `goal` and `time_commitment` from `interview_context`.
   - Confirm at least one tone adaptation from step 6 was applied.

## Output

A single Markdown string (the 1-page roadmap), ready to render in the UI.

## References

- [Roadmap template](./resources/roadmap_template.md)
- [Example output](./examples/sample_roadmap.md)
