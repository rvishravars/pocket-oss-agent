---
name: pocket-oss-agent
description: >-
  Use this skill when the user wants a personalized open-source contribution
  roadmap for a GitHub repository: a one-page plan with a matched good first
  issue, local setup steps, and a maintainer-friendliness read. Triggers on
  requests like "help me contribute to this repo" or "find me a good first
  issue". Entry point that orchestrates the other Pocket OSS Agent skills.
---

# Pocket OSS Agent

Orchestrates the full pipeline for turning "I want to contribute to X" into a
single-screen, personalized roadmap. This skill does not do the work itself -
it sequences the other seven skills and carries their outputs forward as plain
conversation context (no database, no external session store).

## Pipeline

Run these phases in order. Each phase's output is just held in the
conversation - pass it forward by referencing it, not by writing it to any
external store.

1. **Developer Context** - invoke `resume-parser`.
   - If the user hasn't provided a resume, ask for one (file path, pasted
     text, or a quick verbal summary of languages/experience) and proceed
     with whatever they give you rather than blocking on a PDF.

2. **Interview** - invoke `interviewer-agent`.
   - Use the developer context to personalize tone, per that skill's steps.

3. **Repo Investigation** - invoke `github-repo-investigator` on the target
   repo URL. Run this in parallel (conceptually) with steps 4 and 5 below
   once you have `owner`/`repo` parsed - they all read from the same repo
   facts.

4. **Environment Setup** - invoke `env-setup-validator`, using the file tree
   from step 3.

5. **Vibe Check** - invoke `repo-vibe-checker`, using `owner`/`repo` from
   step 3.

6. **Issue Matching** - invoke `skill-matcher`, using the developer context
   (step 1), interview context (step 2), and candidate issues (step 3).

7. **Roadmap** - invoke `contribution-strategy-generator` with all six
   upstream outputs (developer context, interview context, repo facts, setup
   steps, vibe summary, top match) to produce the final Markdown roadmap.

## Notes

- This is a single-agent, in-context implementation: no LangGraph
  orchestrator, no Postgres/pgvector, no GitHub MCP server required. All
  "agent handoffs" are just this skill directing you through the sequence
  above within one conversation.
- If the user only wants one phase (e.g., "just check the vibe of this
  repo"), skip straight to the relevant sub-skill instead of running the
  full pipeline.
- If a phase can't complete (e.g., no resume available, repo is private and
  inaccessible), don't block the whole pipeline - note the gap and continue
  with the remaining phases using reasonable defaults.
