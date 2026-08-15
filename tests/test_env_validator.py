"""Unit coverage for toolchain detection and setup-guide assembly."""

import pytest

from pocket_oss_agent.agents.env_validator import (
    build_setup_steps,
    detect_container_tooling,
    detect_toolchains,
    has_enough_steps,
    parse_makefile_targets,
    parse_package_scripts,
    validate_setup,
)
from pocket_oss_agent.state import RepoFacts, SetupSteps


def facts(*root_files: str) -> RepoFacts:
    return RepoFacts(owner="octo", repo="widget", root_files=list(root_files))


def commands(steps) -> list[str]:
    return [s.command for s in steps]


class TestDetectToolchains:
    @pytest.mark.parametrize(
        ("root", "expected"),
        [
            (["package.json"], "npm"),
            (["package.json", "package-lock.json"], "npm"),
            (["package.json", "yarn.lock"], "yarn"),
            (["package.json", "pnpm-lock.yaml"], "pnpm"),
            (["pyproject.toml"], "pip"),
            (["pyproject.toml", "poetry.lock"], "poetry"),
            (["pyproject.toml", "uv.lock"], "uv"),
            (["requirements.txt"], "pip"),
            (["Cargo.toml"], "cargo"),
            (["go.mod"], "go"),
            (["pom.xml"], "maven"),
            (["build.gradle"], "gradle"),
            (["Gemfile"], "bundler"),
            (["Gemfile", "Gemfile.lock"], "bundler"),
            (["composer.json"], "composer"),
            (["mix.exs"], "mix"),
        ],
    )
    def test_identifies_the_manager(self, root: list[str], expected: str) -> None:
        assert detect_toolchains(root)[0].name == expected

    @pytest.mark.parametrize(
        ("root", "expected"),
        [
            (["package.json", "yarn.lock"], ["yarn"]),
            (["package.json", "pnpm-lock.yaml"], ["pnpm"]),
            (["pyproject.toml", "poetry.lock"], ["poetry"]),
            (["pyproject.toml", "requirements.txt"], ["pip"]),
        ],
    )
    def test_lockfile_suppresses_the_shared_manifest(self, root, expected) -> None:
        """Regression: yarn.lock plus package.json reported "yarn + npm", and the
        guide told the contributor to run two competing installers.
        """
        assert [t.name for t in detect_toolchains(root)] == expected

    def test_polyglot_repo_reports_every_toolchain(self) -> None:
        found = [t.name for t in detect_toolchains(["package.json", "pyproject.toml", "go.mod"])]
        assert set(found) == {"npm", "pip", "go"}

    def test_a_rails_style_app_reports_both_halves(self) -> None:
        """Regression: mastodon carries Gemfile and yarn.lock, and reporting only
        yarn left the contributor with no bundle install step.
        """
        found = [
            t.name
            for t in detect_toolchains(["Gemfile", "Gemfile.lock", "package.json", "yarn.lock"])
        ]
        assert set(found) == {"bundler", "yarn"}

    def test_unrecognised_repo_yields_nothing(self) -> None:
        assert detect_toolchains(["README.md", "LICENSE"]) == []


class TestContainerTooling:
    def test_detects_dockerfile_without_compose(self) -> None:
        has_docker, services, compose = detect_container_tooling(["Dockerfile"])
        assert (has_docker, services, compose) == (True, [], None)

    def test_extracts_compose_service_names(self) -> None:
        text = "services:\n  db:\n    image: postgres\n  redis:\n    image: redis\n"
        has_docker, services, compose = detect_container_tooling(["docker-compose.yml"], text)
        assert has_docker is True
        assert services == ["db", "redis"]
        assert compose == "docker-compose.yml"

    @pytest.mark.parametrize("name", ["compose.yml", "compose.yaml", "docker-compose.yaml"])
    def test_recognises_the_modern_filenames(self, name: str) -> None:
        assert detect_container_tooling([name])[2] == name

    def test_malformed_compose_degrades_to_no_services(self) -> None:
        has_docker, services, _ = detect_container_tooling(["docker-compose.yml"], "{{ not yaml")
        assert (has_docker, services) == (True, [])

    def test_compose_without_a_services_block(self) -> None:
        assert detect_container_tooling(["docker-compose.yml"], "version: '3'")[1] == []

    def test_no_container_tooling(self) -> None:
        assert detect_container_tooling(["README.md"]) == (False, [], None)


class TestParsers:
    def test_reads_package_scripts(self) -> None:
        scripts = parse_package_scripts('{"scripts": {"test": "jest", "build": "tsc"}}')
        assert scripts == {"test": "jest", "build": "tsc"}

    @pytest.mark.parametrize("text", [None, "", "not json", "[]", '{"name": "x"}'])
    def test_unusable_package_json_yields_empty(self, text) -> None:
        assert parse_package_scripts(text) == {}

    def test_reads_makefile_targets(self) -> None:
        text = "install:\n\tpip install .\n\ntest: install\n\tpytest\n\n.PHONY: test\n"
        assert parse_makefile_targets(text) == {"install", "test"}

    def test_ignores_recipes_and_variables(self) -> None:
        text = "CC = gcc\nbuild:\n\t$(CC) main.c\n"
        assert parse_makefile_targets(text) == {"build"}

    def test_no_makefile(self) -> None:
        assert parse_makefile_targets(None) == set()


class TestBuildSetupSteps:
    def _build(self, repo_facts, toolchains, **kwargs):
        return build_setup_steps(
            repo_facts,
            toolchains,
            services=kwargs.get("services", []),
            compose_file=kwargs.get("compose_file"),
            package_scripts=kwargs.get("package_scripts", {}),
            make_targets=kwargs.get("make_targets", set()),
        )

    def test_follows_the_spec_ordering(self) -> None:
        repo = facts("pyproject.toml", "poetry.lock", ".env.example", "docker-compose.yml")
        steps = self._build(
            repo,
            detect_toolchains(repo.root_files),
            compose_file="docker-compose.yml",
            services=["db"],
        )
        text = commands(steps)

        assert text[0] == "git clone https://github.com/octo/widget"
        assert text[1] == "cd widget"
        assert "poetry install" in text
        assert "cp .env.example .env" in text
        assert text.index("cp .env.example .env") < text.index("docker compose up -d  # starts db")
        assert text[-1] == "poetry run pytest"

    def test_every_step_is_unverified_because_nothing_ran(self) -> None:
        repo = facts("package.json")
        steps = self._build(repo, detect_toolchains(repo.root_files))
        assert {s.status for s in steps} == {"unverified"}

    def test_steps_are_numbered_from_one(self) -> None:
        repo = facts("go.mod")
        steps = self._build(repo, detect_toolchains(repo.root_files))
        assert [s.step for s in steps] == list(range(1, len(steps) + 1))

    def test_makefile_targets_take_precedence(self) -> None:
        repo = facts("pyproject.toml")
        steps = self._build(
            repo, detect_toolchains(repo.root_files), make_targets={"install", "test"}
        )
        assert "make install" in commands(steps)
        assert commands(steps)[-1] == "make test"

    def test_falls_back_to_env_sample(self) -> None:
        repo = facts("go.mod", ".env.sample")
        assert "cp .env.sample .env" in commands(
            self._build(repo, detect_toolchains(repo.root_files))
        )

    def test_unknown_toolchain_emits_no_placeholder_command(self) -> None:
        """Regression: a "# no test command detected" comment was emitted as a
        command, which the roadmap rendered as a numbered shell step with a time
        estimate, inviting the contributor to paste a comment into a terminal.
        """
        steps = self._build(facts("README.md"), [])
        assert not any(c.lstrip().startswith("#") for c in commands(steps))
        assert commands(steps) == [
            "git clone https://github.com/octo/widget",
            "cd widget",
        ]

    def test_polyglot_repo_installs_each_toolchain(self) -> None:
        repo = facts("package.json", "requirements.txt")
        text = commands(self._build(repo, detect_toolchains(repo.root_files)))
        assert "npm install" in text
        assert "pip install -r requirements.txt" in text

    def test_undetected_toolchain_fails_the_minimum_length_check(self) -> None:
        """Honest signal: clone and cd is not a setup guide, and the spec's
        three step floor is what surfaces that rather than padding it out.
        """
        assert not has_enough_steps(SetupSteps(setup_steps=self._build(facts("README.md"), [])))

    def test_a_detected_toolchain_clears_the_minimum(self) -> None:
        repo = facts("pyproject.toml")
        assert has_enough_steps(
            SetupSteps(setup_steps=self._build(repo, detect_toolchains(repo.root_files)))
        )


class TestValidateSetupNeedsNoRequestsForAPlainRepo:
    async def test_skips_fetches_when_no_config_files_exist(self) -> None:
        """A repo with nothing to parse must not trigger content requests."""

        class ExplodingClient:
            async def get_file_text(self, *args, **kwargs):  # pragma: no cover
                raise AssertionError("no file should be fetched")

        setup = await validate_setup(facts("go.mod", "README.md"), ExplodingClient())

        assert setup.package_manager == "go"
        assert setup.has_docker is False
        assert has_enough_steps(setup)
