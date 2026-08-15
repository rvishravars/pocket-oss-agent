---
name: contribution-strategy-generator
description: >-
  Use this skill when you need to synthesize a developer's profile and
  repository analysis into a final one-page OSS contribution roadmap. This is
  the final step in the Pocket OSS Agent pipeline — it weaves all upstream
  outputs into a concise, actionable Markdown strategy document.
---

# Contribution Strategy Generator Skill

The "Weaver" step. Takes all upstream outputs and generates the final
1-page contribution roadmap, restricted to a single screen-view.

## Prerequisites

All of the following upstream outputs must be available in the conversation:
- ✅ `resume-parser` → `developer_context`
- ✅ `interviewer-agent` → `interview_context`
- ✅ `github-repo-investigator` → `repo_facts`
- ✅ `skill-matcher` → `top_match` (best-fit issue)
- ✅ `env-setup-validator` → `setup_steps`
- ✅ `repo-vibe-checker` → `vibe_summary`

If any are missing (e.g., the user skipped straight to this skill), fall
back gracefully: omit that section or note it as unavailable rather than
aborting.

## Steps

1. **Load All Inputs**
   - Gather the six upstream outputs from earlier in the conversation.

2. **Architecture Snapshot Section**
   - Use `repo_facts.architecture_snapshot` for a 3-5 bullet summary:
     ```
     ## 🗺️ Architecture Snapshot
     - `src/` — Core library logic
     - `tests/` — Unit and integration tests
     - `docs/` — Documentation (MkDocs)
     ```

3. **First Mile Setup Section**
   - Use `setup_steps`, marking each ✅ (validated) or ⚠️ (unverified):
     ```
     ## 🚀 First Mile Setup
     1. `git clone https://github.com/owner/repo`
     2. `poetry install` ✅
     3. `docker-compose up -d` ✅
     4. `poetry run pytest` ✅
     ```

4. **Personalized Target Section**
   - Use `top_match`: issue title, URL, and match rationale.
     ```
     ## 🎯 Your First Contribution
     **Issue:** [Add support for async Python client](#1234)
     **Why you:** You have 5 years of Python experience with asyncio.
     ```

5. **Vibe Check Section**
   - Use `vibe_summary` and its raw metrics:
     ```
     ## 💬 Vibe Check
     🟢 Highly welcoming — last commit 2 days ago, issues answered in ~1 day.
     Maintainer merge rate: 78%. CONTRIBUTING.md and CoC present.
     ```

6. **Assemble the Final Document**
   - Combine all sections with a personalized header:
     ```markdown
     # OSS Contribution Roadmap: {repo_name}
     > Generated for {developer_name} · {seniority} {domain} engineer
     > 🎯 Goal: {interview_context.goal} · ⏱️ Availability: {interview_context.time_commitment}

     [Architecture Snapshot]
     [First Mile Setup]
     [Your First Contribution]
     [Vibe Check]
     ```
   - Adapt tone based on `interview_context`:
     - `goal:learning` → add a "What you'll learn" callout in the Target section.
     - `goal:career` → add a "How this helps your job search" callout.
     - `time:light` → prepend each setup step with estimated time (e.g. `~2 min`).
     - `risk:low` → open the Target section with a reassurance line.
   - Enforce a **single screen-view** constraint: total output ≤ 60 lines.
   - If any section exceeds its budget, truncate with `…` rather than
     cutting a section entirely.

7. **Verify**
   - The document must contain all available sections (fewer if some
     upstream inputs were missing — never fabricate a section).
   - Total line count ≤ 60.
   - All issue URLs are non-empty strings starting with `https://`.
   - The header includes both `goal` and `time_commitment` if
     `interview_context` is available.
   - At least one tone adaptation from step 6 was applied, if applicable.

## Output

A single Markdown string (the roadmap), ready to hand back to the user.
