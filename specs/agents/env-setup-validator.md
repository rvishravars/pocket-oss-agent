---
agent: env-setup-validator
position: 4
consumes: [repo_facts]
produces: setup_steps
tooling: GitHub REST API via httpx; sandbox runner still required for step 5
status: implemented except step 5
---

# Env Setup Validator

Detects the repository toolchain and produces a validated local setup guide.
Populates the "First Mile Setup" section of the roadmap.
Runs after `github-repo-investigator`, in parallel with `repo-vibe-checker`.

## Inputs

| Key | Source | Required |
|-----|--------|----------|
| `repo_facts` | `github-repo-investigator` | Yes |

Abort with a descriptive error if `repo_facts` is absent.

## Prerequisites

- GitHub MCP Server is accessible for fetching individual config files.
- A sandboxed runner is available for dry-run validation.

## Output

Writes `setup_steps` to the session state object.

```json
{
  "package_manager": "pip + poetry",
  "has_docker": true,
  "docker_services": ["db", "redis", "app"],
  "setup_steps": [
    { "step": 1, "command": "git clone https://github.com/...", "status": "validated" },
    { "step": 2, "command": "poetry install", "status": "validated" },
    { "step": 3, "command": "cp .env.example .env", "status": "unverified" },
    { "step": 4, "command": "docker-compose up -d", "status": "validated" },
    { "step": 5, "command": "poetry run pytest", "status": "validated" }
  ]
}
```

## Steps

1. **Detect the package manager**
   - Read `repo_facts.root_files`, gathered by the investigator, so the common
     path costs no extra requests.
   - Markers are grouped by ecosystem, and within an ecosystem the most specific
     marker wins. A lockfile must **suppress** the manifest it shares, not merely
     outrank it: `package.json` beside `yarn.lock` otherwise reports "yarn + npm"
     and the guide tells the contributor to run two competing installers.
   - Report one toolchain per ecosystem present, since a repository can span
     several. mastodon carries both `Gemfile` and `yarn.lock`, and omitting
     either leaves the contributor without a working install.
   - Recognised ecosystems: js, python, ruby, php, elixir, rust, go, jvm.
   - Scan for:
     | File | Package Manager |
     |------|----------------|
     | `package.json` | npm / yarn / pnpm |
     | `requirements.txt` / `pyproject.toml` | pip / poetry |
     | `pom.xml` / `build.gradle` | Maven / Gradle |
     | `go.mod` | Go modules |
     | `Cargo.toml` | Rust / Cargo |
   - Fetch the matched file through MCP to disambiguate, for example reading
     the `packageManager` field or a lockfile name.

2. **Detect container tooling**
   - Check for `Dockerfile`, `docker-compose.yml`, `devcontainer.json`.
   - Extract the `services` keys from `docker-compose.yml`.

3. **Detect build and test scripts**
   - `Makefile` targets: `build`, `test`, `dev`.
   - `package.json` scripts: `build`, `test`, `dev`, `start`.
   - Code-fenced commands in `repo_facts.contributing_summary`.

4. **Generate setup instructions**
   - Assemble in order:
     1. Clone
     2. Dependency install
     3. Environment setup, copying `.env.example` if present
     4. Docker or service startup
     5. Test run, to prove the environment works

5. **Dry-run validation**
   - **Not implemented.** Running a repository's own install and test commands
     executes arbitrary code from an untrusted public repository, so this needs
     container isolation, a network policy and timeouts before it can ship.
     Until then every step is reported `unverified`.
   - Execute steps 2 through 5 in the sandbox and record exit codes.
   - Mark a zero exit code `validated`.
   - Mark a non-zero exit code or a skipped step `unverified`.
   - Never mark a step `validated` without having run it.
     A fabricated green checkmark is worse than an honest warning, because the
     roadmap presents these as confirmed.

6. **Verify**
   - The list has at least 3 steps.
   - Every step carries an explicit `validated` or `unverified` status.

## References

- `scripts/detect_setup.py`
- `examples/setup_output.json`
