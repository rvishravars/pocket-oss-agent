<div align="center">

# 🚀 Pocket OSS Agent

**Your AI-powered co-pilot for open-source contribution.**  
Drop your resume. Pick a repo. Get a personalized, one-page contribution roadmap in seconds.

[![CI](https://github.com/rvishravars/pocket-oss-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/rvishravars/pocket-oss-agent/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-violet.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python&logoColor=white)](https://python.org)
[![LangGraph](https://img.shields.io/badge/Orchestration-LangGraph-orange)](https://github.com/langchain-ai/langgraph)
[![PostgreSQL](https://img.shields.io/badge/Database-PostgreSQL+pgvector-336791?logo=postgresql&logoColor=white)](https://github.com/pgvector/pgvector)
[![GitHub API](https://img.shields.io/badge/Tooling-GitHub%20REST%20API-181717?logo=github&logoColor=white)](https://docs.github.com/rest)

</div>

---

## ✨ What is this?

Getting started with open source is hard. You don't know which issue to pick, whether maintainers are active, or if your skills even match the codebase.

**Pocket OSS Agent** solves this with a multi-agent AI pipeline that:
1. Reads your resume to understand your skills
2. Interviews you to understand your *goals*
3. Investigates the target GitHub repo through the GitHub API
4. Finds the single best issue for you - semantically, not just by label
5. Delivers a **one-page contribution roadmap** tailored to you

---

## 🎯 User Flow

```
Login → Upload Resume → Interview → Pick Repo → Agentic Analysis → 1-Page Roadmap
```

| Step | What happens |
|------|-------------|
| 1. **Authentication** | Google OAuth 2.0 *(planned, not built)* |
| 2. **Profile Ingestion** | AI parses your PDF resume into a structured Developer Context |
| 3. **Interactive Discovery** | Interviewer Agent clarifies your goals, time budget, and preferences |
| 4. **Project Selection** | You provide any public GitHub repository URL |
| 5. **Agentic Analysis** | Resume Agent + Repo Agent work in parallel |
| 6. **Strategy Generation** | Weaver Agent synthesizes everything into a single-screen roadmap |

---

## 🤖 Agent Architecture

Seven specialized agents, orchestrated as a [LangGraph](https://github.com/langchain-ai/langgraph) DAG behind a FastAPI service:

```mermaid
graph TD
    Client[Client] -->|POST /sessions| Start(( ))
    Start --> Parse[resume-parser]
    Start --> Inv[github-repo-investigator]

    Parse --> Intv[interviewer-agent]
    Intv -.->|graph pauses| Wait{{POST /interview}}
    Wait -.->|resumes| Match

    Inv --> Setup[env-setup-validator]
    Inv --> Vibe[repo-vibe-checker]
    Inv --> Match[skill-matcher]
    Intv --> Match

    Match --> Road[contribution-strategy-generator]
    Setup --> Road
    Vibe --> Road
    Road -->|GET /roadmap| Output[1-Page Roadmap]

    Parse -.-> LLM[Claude Haiku 4.5]
    Inv -.-> GH[GitHub REST API]
    Match -.-> Vec[(Vector store)]
```

The interview is the only step needing a human mid-run, so the graph interrupts
there and a checkpointer holds the state across the request that answers it.
The whole repository branch keeps running while it waits.

| Agent | Role | Status |
|-------|------|--------|
| **Resume Parser** | Extracts name, languages, frameworks, seniority and domain from a PDF | ✅ Built |
| **Interviewer** | Asks 4 to 5 targeted questions to capture contribution intent | ✅ Built |
| **Repo Investigator** | Builds a repo fact sheet: layout, candidate issues, PR velocity | ✅ Built |
| **Env Setup Validator** | Detects the toolchain and drafts the First Mile guide | ✅ Built |
| **Vibe Checker** | Scores maintainer responsiveness and welcome signals | ✅ Built |
| **Skill Matcher** | Ranks candidate issues against the developer profile | ✅ Built |
| **Strategy Generator** | Weaves all signals into the final one-page roadmap | ✅ Built |

All seven are implemented with 100% test and branch coverage, wired into the
graph and reachable over HTTP.

Two known gaps, both recorded in the specs rather than papered over:

- **Issue matching does not fire yet.** The similarity floor inherited from the
  spec is roughly twice too high: measured against real repositories the best
  match scores about 0.34 against a 0.40 cutoff, so every roadmap currently
  falls back to browsing issues manually. The ranking itself is correct and
  separates relevant from irrelevant cleanly; it is the cutoff that needs
  calibrating. See `specs/agents/skill-matcher.md`.
- **Setup steps are never marked verified**, because executing an untrusted
  repository's own install commands needs a sandbox that does not exist yet.

---

## 🌟 Core Features

### 🧠 Intelligent Skill Matching
Semantic similarity between your resume profile plus interview answers and the
repository's open issues, not just keyword matching. The store sits behind a
protocol: in-memory by default, `pgvector` for production. Note the cutoff is
still being calibrated, so matching is not yet returning a pick on real repos.

### 🔍 Token-Efficient GitHub Access
Agents summarize repository data (issue lists, file trees, PR history) before any of it reaches an LLM. Nodes that fetch a fixed sequence deterministically use the GitHub REST API directly; the MCP Server is reserved for paths where an LLM chooses its own tools.

### 💬 Vibe Check
Real-time sentiment analysis on maintainer responsiveness: commit recency, issue response time, PR merge rate, and contributor-welcome signals.

### 🚀 First Mile Setup
Auto-detects your repo's toolchain (Docker, Poetry, npm, Gradle, etc.) and generates a validated step-by-step local environment setup.

---

## 📄 The One-Page Roadmap

Every roadmap fits in a single screen and contains four sections.
Setup steps are marked ⚠️ until the sandboxed dry run lands, because a step is
never reported verified without having been executed:

```markdown
# OSS Contribution Roadmap: {repo}
> 🎯 Goal: portfolio · ⏱️ Availability: light (~5 hrs/week)

## 🗺️ Architecture Snapshot
- `src/` - Core library logic
- `tests/` - Unit and integration tests

## 🚀 First Mile Setup
1. `git clone ...` ⚠️ _~1 min_
2. `uv sync` ⚠️ _~2 min_
3. `docker compose up -d` ⚠️ _~3 min_
> ⚠️ Steps are inferred from config files, not yet executed.

## 🎯 Your First Contribution
**Issue:** Add support for async Python client
**Why you:** 5 years Python + asyncio. Matches your portfolio goal.

## 💬 Vibe Check
🟢 Highly welcoming - last commit 2 days ago, issues answered in ~1 day.
```

---

## 🛠️ Technical Stack

| Layer | Technology |
|-------|-----------|
| **AI Model** | Claude Haiku 4.5 for resume extraction (single-shot structured output) |
| **Orchestration** | Python · FastAPI · LangGraph |
| **Embeddings** | sentence-transformers, behind a protocol *(optional extra)* |
| **Database** | PostgreSQL + `pgvector` *(implemented, not yet exercised against a live database)* |
| **GitHub Tooling** | GitHub REST API; MCP Server where an LLM picks tools |
| **UI** | Streamlit or Next.js *(planned)* |

---

## 🤖 Agent Skills

The seven agents are specified under `specs/agents/`.
These are product specifications that the implementation is written against, not
tooling for a coding assistant:

| Skill | Purpose |
|-------|---------|
| [`interviewer-agent`](specs/agents/interviewer-agent.md) | Dynamic pre-analysis discovery interview |
| [`resume-parser`](specs/agents/resume-parser.md) | Structured developer profile extraction from PDF |
| [`github-repo-investigator`](specs/agents/github-repo-investigator.md) | Deep repo analysis via the GitHub API |
| [`skill-matcher`](specs/agents/skill-matcher.md) | Semantic issue matching with interview filters |
| [`env-setup-validator`](specs/agents/env-setup-validator.md) | Auto-detect toolchain + generate First Mile setup |
| [`repo-vibe-checker`](specs/agents/repo-vibe-checker.md) | Contributor-friendliness sentiment analysis |
| [`contribution-strategy-generator`](specs/agents/contribution-strategy-generator.md) | Weaves all outputs into the final 1-page roadmap |

---

## 🗺️ Roadmap

- [x] `github-repo-investigator` - repo fact sheet from a URL
- [x] `repo-vibe-checker` - maintainer responsiveness and welcome signals
- [x] `env-setup-validator` - toolchain detection and First Mile guide
- [x] `interviewer-agent` - headless discovery interview
- [x] `contribution-strategy-generator` - the one-page roadmap
- [x] `resume-parser` - PDF extraction + Claude structured output
- [x] `skill-matcher` - semantic issue matching
- [x] LangGraph orchestration + FastAPI
- [ ] Calibrate the similarity threshold, so matching actually returns a pick
- [ ] Sandboxed dry run, so setup steps can be marked verified
- [ ] Postgres checkpointer and pgvector against a live database
- [ ] Streamlit MVP demo, then Next.js production UI
- [ ] Auth (Google OAuth 2.0)

---

## 🧪 Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

pytest -q                 # fully offline: no API key, no model download, no database
pytest -m live            # opt in to the paid-API checks (deselected by default)
ruff check . && ruff format --check .

uvicorn pocket_oss_agent.api:create_app --factory --reload   # serve the API
```

### The API

The interview needs a human mid-run, so a session is a resource that spans two
requests:

| Endpoint | Does |
|----------|------|
| `POST /sessions` | Start a run. Returns a session id and the interview questions |
| `GET /sessions/{id}` | Status, plus the questions while paused |
| `POST /sessions/{id}/interview` | Submit answers; resumes the graph |
| `GET /sessions/{id}/roadmap` | The finished Markdown |

Repository analysis, the vibe check and setup detection all run while the
interview waits, so answering is the only thing on the critical path.

Inputs the caller got wrong return `422` (unreadable resume, malformed repo
URL); asking for a roadmap before answering returns `409`.

Supported on Python 3.11 through 3.14.

The default suite reaches nothing external.
The LLM, the embedder and the vector store are injected behind protocols, so
tests run against fakes with no API key, no model download and no database.
CI never spends money and cannot.

Two things are opt-in:

- `GITHUB_TOKEN` to run the agents against a real repository via
  `scripts/run_pipeline.py`.
- `pytest -m live` for the handful of checks that call the paid Claude API.
  These are deselected by default everywhere, and skipped outright without a
  credential.

---

## 🤝 Contributing

Contributions are welcome! Please open an issue first to discuss what you'd like to change.

---

## 📄 License

MIT © [rvishravars](https://github.com/rvishravars)
