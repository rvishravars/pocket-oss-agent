# Claude Code Project Memory

Shared agent context for this repository lives in `AGENTS.md`, imported below.
Keep project-wide facts in `AGENTS.md` so Antigravity and Claude Code stay in sync.
Claude-only rules belong in this file.

@AGENTS.md

## Authoring Guidelines

- Never use the em dash character (U+2014). Use a plain dash "-" instead.
- When writing commit messages, NEVER auto-add your agent name as co-author.
- Never manually modify CHANGELOG.md files or any files that are marked as auto-generated.
- When writing or substantially editing long Markdown files, put each full sentence on its own line.
  Preserve normal Markdown structure, but avoid wrapping multiple sentences onto one physical line.

## Engineering Guidelines

- When making technical decisions, do not give much weight to development cost.
  Instead, prefer quality, simplicity, robustness, scalability, and long-term maintainability.
- When doing bug fixes, always start with reproducing the bug in an E2E setting as closely aligned with how an end user experiences it.
  This makes sure you find the real problem so your fix will actually solve it.
- When end-to-end testing a product, be picky about the UI you see and be obsessed with pixel perfection.
  If something clearly looks off, even if it is not directly related to what you are doing, try to get it fixed along the way.
- Apply that same high standard to engineering excellence: lint, test failures, and test flakiness.
  If you see one, even if it is not caused by what you are working on right now, still get it fixed.

## Skills

This repository has no `.claude/skills/` directory, and that is intentional.
Skills auto-trigger on the phrasing used while developing, so if the product's seven
runtime agents lived there they would shadow the real implementation during testing.
Their specifications are in `specs/agents/` instead.

Do not add a skill that performs a pipeline agent's job.
A skill here should encode development conventions, such as LangGraph node structure
or how to run the agent evals, and only once there is code for it to describe.

`.claude/commands/` holds a conversational prototype of the pipeline.
Slash commands only run when typed explicitly, so they are safe.
They are not reconciled with `specs/agents/` and are not authoritative.
