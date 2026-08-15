---
name: env-setup-validator
description: >-
  Use this skill when you need to generate and validate local environment
  setup commands for a GitHub repository. Detects Docker, build scripts, and
  package managers from the repo's file tree to produce a verified "First
  Mile" setup guide.
---

# Env Setup Validator Skill

Generates a step-by-step local environment setup guide for a repository.
Output is used in the "First Mile Setup" section of the final roadmap.

## Prerequisites

- Repository file tree is available (from `github-repo-investigator`), or
  a local clone of the repo to inspect directly.

## Steps

1. **Detect Package Manager**
   - Scan the root file tree for known config files:
     | File | Package Manager |
     |------|----------------|
     | `package.json` | npm / yarn / pnpm |
     | `requirements.txt` / `pyproject.toml` | pip / poetry |
     | `pom.xml` / `build.gradle` | Maven / Gradle |
     | `go.mod` | Go modules |
     | `Cargo.toml` | Rust / Cargo |
   - Record the detected package manager(s). If working from a repo fact
     sheet rather than a local clone, fetch specific files as needed:
     ```bash
     gh api repos/{owner}/{repo}/contents/package.json
     ```

2. **Detect Container Tooling**
   - Check for `Dockerfile`, `docker-compose.yml`, `devcontainer.json`.
   - If `docker-compose.yml` exists, extract the `services` keys as a list.

3. **Detect Build/Test Scripts**
   - Check `Makefile` for common targets: `build`, `test`, `dev`.
   - Check `package.json`'s `scripts` block for `build`, `test`, `dev`, `start`.
   - Check the `CONTRIBUTING.md` summary (from `github-repo-investigator`)
     for any code-fenced setup commands.

4. **Generate Setup Instructions**
   - Assemble a sequential list of commands:
     1. Clone command
     2. Dependency install (based on detected package manager)
     3. Environment setup (`.env.example` copy if present)
     4. Docker/service startup (if detected)
     5. Run tests (to verify the environment)
   - Format as a numbered Markdown list with code blocks.

5. **Dry-Run Validation (if you have a local clone)**
   - If you've actually cloned the repo and have shell access to it, run
     steps 2-5 for real and record exit codes.
   - If working only from the fact sheet (no local clone), skip execution
     and mark every step ⚠️ **Unverified** rather than guessing at results.

6. **Verify**
   - Confirm the generated setup list has ≥ 3 steps.
   - Mark each step ✅ **Validated** (actually ran) or ⚠️ **Unverified**
     (inferred from config files only).

## Output Schema

```json
{
  "package_manager": "pip + poetry",
  "has_docker": true,
  "docker_services": ["db", "redis", "app"],
  "setup_steps": [
    { "step": 1, "command": "git clone https://github.com/...", "status": "validated" },
    { "step": 2, "command": "poetry install", "status": "unverified" },
    { "step": 3, "command": "cp .env.example .env", "status": "unverified" },
    { "step": 4, "command": "docker-compose up -d", "status": "unverified" },
    { "step": 5, "command": "poetry run pytest", "status": "unverified" }
  ]
}
```
