# Pocket OSS Agent - Shared Agent Context

This file is automatically loaded by both **Antigravity (Gemini)** and **Claude Code**.
It provides shared project context for all AI agents working in this repository.

---

## Project Summary

**Pocket OSS Agent** is a mobile-ready, AI-driven platform that generates a
personalized, one-page open-source contribution roadmap for any developer.
It ingests a PDF resume, conducts a short interview, analyzes a GitHub repository,
and outputs a single-screen Markdown strategy document.

---

## Agent Pipeline (Execution Order)

```
resume-parser ──────────→ interviewer-agent ─────────────┐
  (developer_context)        (interview_context)         │
                                                         ↓
github-repo-investigator ───────────────────────→ skill-matcher
  (repo_facts)                                      (top_match)
        │                                                │
        ├──→ repo-analyst (repo_intelligence, cached) ───┤
        ├──→ env-setup-validator (setup_steps) ──────────┤
        │                                                ↓
        └──→ repo-vibe-checker (vibe_summary) ──→ contribution-strategy-generator
                                                         ↓
                                                   1-Page Roadmap
```

`resume-parser` and `github-repo-investigator` have no dependency on each other
and run in parallel.
`interviewer-agent` requires `developer_context` to personalize its phrasing, so
it runs after `resume-parser`, never before.
`repo-analyst`, `env-setup-validator` and `repo-vibe-checker` all depend only
on `repo_facts` and run in parallel.

All agent outputs are stored in a **session state object** passed between steps.
No agent should assume it is the only consumer of its output.

`graph.py` implements this as a LangGraph DAG.
The interview is the one step needing a human mid-run, so the graph interrupts
there and a checkpointer holds the state across the HTTP request that answers it.
Everything on the repository branch keeps running while it waits.

`repo-analyst` is a real node in this graph, but it is not like the other
seven: it checks `RepoIntelligenceStore` before doing any work, so a repeat
request for an already-analyzed repository costs nothing here. Its output,
`repo_intelligence`, is a **nullable enrichment** everywhere it is consumed -
`skill-matcher` and `contribution-strategy-generator` both render correctly
without it, the same way a `skill-matcher` miss already renders a fallback
rather than aborting the run. See `specs/agents/repo-analyst.md`.

---

## Session State Schema

Each agent reads from and writes to a shared session object:

```json
{
  "user_id": "string",
  "developer_context": { },      // from: resume-parser
  "interview_context": { },      // from: interviewer-agent
  "repo_facts": { },             // from: github-repo-investigator
  "repo_intelligence": { },      // from: repo-analyst (nullable - cache-backed, may not be warm yet)
  "vibe_summary": { },           // from: repo-vibe-checker
  "setup_steps": [ ],            // from: env-setup-validator
  "top_match": { },              // from: skill-matcher
  "roadmap": "string"            // from: contribution-strategy-generator
}
```

---

## Key Constraints

- **Output length:** The final roadmap must fit in ≤ 60 lines (single screen-view).
- **Token efficiency:** Summarize all GitHub data before passing to LLM. Never pass raw file trees or full issue bodies.
- **Embedding model consistency:** All pgvector embeddings must use the same model (e.g., `text-embedding-004`).
- **Interview first:** The `interviewer-agent` must run before `skill-matcher` and `contribution-strategy-generator`. Its output is a required input for both.
- **Fail loudly:** If a required upstream output is missing, abort with a descriptive error - do not silently default.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Orchestration | Python · FastAPI · LangGraph |
| Database | PostgreSQL + `pgvector` extension |
| GitHub Tooling | GitHub REST API for deterministic nodes; MCP Server where an LLM chooses tools |
| Auth | Google OAuth 2.0 |
| UI | Streamlit (MVP) / Next.js (production) |

---

## Agent Specifications

These are specifications for the production agents, not tooling for the coding agent.
They are the contract that the Python implementation is written against.
See `specs/agents/README.md` for provenance and open reconciliation work.

| Agent | Spec | Production Tooling |
|-------|------|--------------------|
| `interviewer-agent` | `specs/agents/interviewer-agent.md` | UI chat/form |
| `resume-parser` | `specs/agents/resume-parser.md` | PDF extraction, LLM |
| `github-repo-investigator` | `specs/agents/github-repo-investigator.md` | GitHub MCP Server |
| `skill-matcher` | `specs/agents/skill-matcher.md` | pgvector |
| `env-setup-validator` | `specs/agents/env-setup-validator.md` | GitHub MCP Server |
| `repo-vibe-checker` | `specs/agents/repo-vibe-checker.md` | GitHub MCP Server |
| `contribution-strategy-generator` | `specs/agents/contribution-strategy-generator.md` | LLM |

---

## Repository Structure

```
pocket-oss-agent/
├── AGENTS.md                  ← this file (shared context)
├── CLAUDE.md                  ← Claude-specific rules, imports AGENTS.md
├── idea.md                    ← original product specification
├── README.md                  ← public-facing documentation
├── Dockerfile                 ← one image, shared by both compose services
├── docker-compose.yml         ← api + ui services, api healthchecked before ui starts
├── .env.example               ← credential template; copy to .env (gitignored)
├── src/pocket_oss_agent/
│   ├── graph.py               ← LangGraph orchestration of the seven agents
│   ├── api.py                 ← FastAPI surface over the graph
│   └── agents/                ← the seven agent implementations
├── scripts/
│   ├── run_pipeline.py        ← run the agents against a real repo, no server
│   └── streamlit_app.py       ← demo UI, a thin client over the FastAPI surface
├── specs/
│   └── agents/                ← production agent specifications
└── .claude/
    └── commands/              ← Claude Code slash commands (manual prototype)
```

`scripts/` holds dev tooling verified by running it, not by the pytest suite -
that is why the coverage gate only tracks `src/pocket_oss_agent`.

`.claude/skills/` and `.agents/skills/` are both deliberately absent.
Agent skills are development tooling that auto-triggers while writing code, so
shipping the product's runtime agents there caused them to shadow the real
implementation during testing.
That applies equally to Claude Code and Antigravity.
The single source of truth is `specs/agents/`, which both assistants can read
through this file without any auto-trigger behaviour.
