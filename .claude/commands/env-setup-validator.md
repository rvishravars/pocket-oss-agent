# Validate Environment Setup

Auto-detect the repository's toolchain and generate a validated First Mile setup guide.

## Prerequisites
Requires `repo_facts` in session state (from `/github-repo-investigator`).

## Steps

1. **Detect package manager** from root file tree:
   | File | Manager |
   |------|---------|
   | `package.json` | npm / yarn / pnpm |
   | `requirements.txt` / `pyproject.toml` | pip / poetry |
   | `pom.xml` / `build.gradle` | Maven / Gradle |
   | `go.mod` | Go modules |
   | `Cargo.toml` | Cargo |

2. **Detect container tooling**: look for `Dockerfile`, `docker-compose.yml`, `devcontainer.json`.

3. **Detect build/test scripts**: check `Makefile` targets and `package.json` scripts block.

4. **Assemble setup steps** in order:
   1. `git clone <repo_url>`
   2. Dependency install command
   3. `cp .env.example .env` (if `.env.example` exists)
   4. Docker/service startup (if detected)
   5. Run tests (to verify environment)

5. Mark each step as `validated` (if you can confirm it's standard) or `unverified`.

6. Store as `setup_steps`:

```json
[
  { "step": 1, "command": "git clone ...", "estimated_minutes": 1, "status": "validated" },
  { "step": 2, "command": "poetry install", "estimated_minutes": 3, "status": "validated" }
]
```

7. Tell user to run `/repo-vibe-checker` next.
