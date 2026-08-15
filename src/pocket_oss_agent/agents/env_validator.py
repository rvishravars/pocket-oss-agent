"""env-setup-validator: build a First Mile setup guide for a repository.

Implements steps 1 to 4 and 6 of `specs/agents/env-setup-validator.md`.

Step 5, the sandboxed dry run, is **not implemented**. Executing a repository's
own install and test commands runs arbitrary code from an untrusted public
repository, so it needs real isolation before it can ship. Until then every step
is reported `unverified`, which the spec requires: a step is never marked
validated without having been run.

Detection reads `repo_facts.root_files`, already gathered by the investigator,
so the common path costs no extra requests. Only `package.json`,
`docker-compose.yml` and `Makefile` are fetched, and only when present.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, NamedTuple

import yaml

from ..github_client import GitHubClient
from ..state import RepoFacts, SetupStep, SetupSteps

COMPOSE_FILENAMES = ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml")
CONTAINER_FILENAMES = ("Dockerfile", "devcontainer.json", *COMPOSE_FILENAMES)
MIN_SETUP_STEPS = 3


class Toolchain(NamedTuple):
    """A detected package manager and the commands that drive it."""

    name: str
    install: str
    test: str


#: ``(marker, ecosystem, toolchain)`` ordered most specific first within each
#: ecosystem. Grouping matters: `package.json` is shared by npm, yarn and pnpm,
#: so a lockfile has to suppress it rather than merely outrank it. Without the
#: ecosystem key, a yarn project reports "yarn + npm" and the guide tells the
#: contributor to run two competing installers.
TOOLCHAIN_MARKERS: tuple[tuple[str, str, Toolchain], ...] = (
    ("pnpm-lock.yaml", "js", Toolchain("pnpm", "pnpm install", "pnpm test")),
    ("yarn.lock", "js", Toolchain("yarn", "yarn install", "yarn test")),
    ("package-lock.json", "js", Toolchain("npm", "npm install", "npm test")),
    ("package.json", "js", Toolchain("npm", "npm install", "npm test")),
    ("uv.lock", "python", Toolchain("uv", "uv sync", "uv run pytest")),
    ("poetry.lock", "python", Toolchain("poetry", "poetry install", "poetry run pytest")),
    ("Pipfile.lock", "python", Toolchain("pipenv", "pipenv install --dev", "pipenv run pytest")),
    ("pyproject.toml", "python", Toolchain("pip", "pip install -e .", "pytest")),
    ("requirements.txt", "python", Toolchain("pip", "pip install -r requirements.txt", "pytest")),
    ("Gemfile.lock", "ruby", Toolchain("bundler", "bundle install", "bundle exec rspec")),
    ("Gemfile", "ruby", Toolchain("bundler", "bundle install", "bundle exec rspec")),
    ("composer.lock", "php", Toolchain("composer", "composer install", "composer test")),
    ("composer.json", "php", Toolchain("composer", "composer install", "composer test")),
    ("mix.exs", "elixir", Toolchain("mix", "mix deps.get", "mix test")),
    ("Cargo.toml", "rust", Toolchain("cargo", "cargo build", "cargo test")),
    ("go.mod", "go", Toolchain("go", "go mod download", "go test ./...")),
    ("pom.xml", "jvm", Toolchain("maven", "mvn install", "mvn test")),
    ("build.gradle", "jvm", Toolchain("gradle", "./gradlew build", "./gradlew test")),
    ("build.gradle.kts", "jvm", Toolchain("gradle", "./gradlew build", "./gradlew test")),
)


def detect_toolchains(root_files: list[str]) -> list[Toolchain]:
    """Return one toolchain per ecosystem present, most specific marker winning.

    A repository can legitimately span several ecosystems, for instance a Python
    backend beside a JavaScript frontend, so all of them are reported. Within
    one ecosystem only the most specific marker counts.
    """
    present = set(root_files)
    found: list[Toolchain] = []
    claimed: set[str] = set()

    for marker, ecosystem, toolchain in TOOLCHAIN_MARKERS:
        if marker in present and ecosystem not in claimed:
            claimed.add(ecosystem)
            found.append(toolchain)
    return found


def detect_container_tooling(root_files: list[str], compose_text: str | None = None):
    """Return ``(has_docker, service_names, compose_filename)``.

    Service names come from parsing the compose file. A malformed one yields an
    empty list rather than an error: the setup guide is still useful without it.
    """
    present = set(root_files)
    has_docker = any(name in present for name in CONTAINER_FILENAMES)
    compose_file = next((name for name in COMPOSE_FILENAMES if name in present), None)

    services: list[str] = []
    if compose_text:
        try:
            parsed = yaml.safe_load(compose_text)
        except yaml.YAMLError:
            parsed = None
        if isinstance(parsed, dict) and isinstance(parsed.get("services"), dict):
            services = [str(key) for key in parsed["services"]]

    return has_docker, services, compose_file


def parse_package_scripts(package_json_text: str | None) -> dict[str, str]:
    """Return the `scripts` block of a package.json, or an empty mapping."""
    if not package_json_text:
        return {}
    try:
        parsed = json.loads(package_json_text)
    except json.JSONDecodeError:
        return {}
    scripts = parsed.get("scripts") if isinstance(parsed, dict) else None
    return {str(k): str(v) for k, v in scripts.items()} if isinstance(scripts, dict) else {}


def parse_makefile_targets(makefile_text: str | None) -> set[str]:
    """Return the target names declared in a Makefile.

    A deliberately shallow parse: a target is a line starting at column zero
    with a name followed by a colon. Enough to tell whether `make test` exists.
    """
    if not makefile_text:
        return set()

    targets: set[str] = set()
    for line in makefile_text.splitlines():
        if not line or line[0].isspace() or line.startswith((".", "#")):
            continue
        name, separator, _ = line.partition(":")
        if separator and name.strip() and " " not in name.strip():
            targets.add(name.strip())
    return targets


def build_setup_steps(
    repo_facts: RepoFacts,
    toolchains: list[Toolchain],
    *,
    services: list[str],
    compose_file: str | None,
    package_scripts: dict[str, str],
    make_targets: set[str],
) -> list[SetupStep]:
    """Assemble the ordered command list described by the spec.

    Every step is `unverified`, because nothing here has been executed. See the
    module docstring.
    """
    commands: list[str] = [f"git clone https://github.com/{repo_facts.slug}"]
    commands.append(f"cd {repo_facts.repo}")

    if "install" in make_targets:
        commands.append("make install")
    else:
        commands.extend(toolchain.install for toolchain in toolchains)

    if ".env.example" in repo_facts.root_files:
        commands.append("cp .env.example .env")
    elif ".env.sample" in repo_facts.root_files:
        commands.append("cp .env.sample .env")

    if compose_file:
        suffix = f"  # starts {', '.join(services)}" if services else ""
        commands.append(f"docker compose up -d{suffix}")

    commands.append(
        _test_command(toolchains, package_scripts=package_scripts, make_targets=make_targets)
    )

    return [
        SetupStep(step=index, command=command, status="unverified")
        for index, command in enumerate(commands, start=1)
    ]


async def validate_setup(repo_facts: RepoFacts, client: GitHubClient) -> SetupSteps:
    """Detect the toolchain and produce the First Mile setup guide."""
    root_files = repo_facts.root_files
    owner, repo = repo_facts.owner, repo_facts.repo

    toolchains = detect_toolchains(root_files)
    _, _, compose_file = detect_container_tooling(root_files)

    package_json_text, compose_text, makefile_text = await asyncio.gather(
        _fetch_if_present(client, owner, repo, "package.json", root_files),
        _fetch_if_present(client, owner, repo, compose_file, root_files),
        _fetch_if_present(client, owner, repo, "Makefile", root_files),
    )

    has_docker, services, compose_file = detect_container_tooling(root_files, compose_text)
    steps = build_setup_steps(
        repo_facts,
        toolchains,
        services=services,
        compose_file=compose_file,
        package_scripts=parse_package_scripts(package_json_text),
        make_targets=parse_makefile_targets(makefile_text),
    )

    return SetupSteps(
        package_manager=" + ".join(t.name for t in toolchains) or None,
        has_docker=has_docker,
        docker_services=services,
        setup_steps=steps,
    )


def has_enough_steps(setup: SetupSteps) -> bool:
    """Spec verification: a usable guide carries at least three steps."""
    return len(setup.setup_steps) >= MIN_SETUP_STEPS


def _test_command(
    toolchains: list[Toolchain], *, package_scripts: dict[str, str], make_targets: set[str]
) -> str:
    """Pick the command most likely to actually run this project's tests."""
    if "test" in make_targets:
        return "make test"
    if "test" in package_scripts and toolchains:
        runner = next((t for t in toolchains if t.name in {"npm", "yarn", "pnpm"}), None)
        if runner:
            return runner.test
    if toolchains:
        return toolchains[0].test
    return "# no test command detected, check CONTRIBUTING.md"


async def _fetch_if_present(
    client: GitHubClient, owner: str, repo: str, path: str | None, root_files: list[str]
) -> Any | None:
    """Fetch a root file only when the tree says it exists."""
    if not path or path not in root_files:
        return None
    return await client.get_file_text(owner, repo, path)
