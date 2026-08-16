"""Coverage for the repo-analyst synthesis call and prompt assembly.

Exercised against a fake Claude client, same as `test_llm.py`, so the suite
needs no API key. What is tested is this wrapper's own logic: the request it
builds, the failure modes, and the "every candidate issue covered" contract
`specs/agents/repo-analyst.md` requires.
"""

import pytest

from pocket_oss_agent.agents.repo_analyst import (
    MODEL,
    ClaudeRepoAnalyzer,
    IssueAnalysis,
    IssueMaterial,
    RepoAnalysis,
    _build_prompt,
)
from pocket_oss_agent.errors import RepoAnalysisFailed
from pocket_oss_agent.state import RepoIntelligence

from . import fixtures

FACTS = fixtures.repo_facts()

ISSUE_MATERIAL = [
    IssueMaterial(
        issue_id=1234,
        title="Add support for an async Python client",
        labels=["good first issue", "python"],
        body="The client blocks on every request. We should add an asyncio-based variant.",
        comments=["I can confirm this. A maintainer here - happy to review a PR."],
    ),
    IssueMaterial(
        issue_id=1240,
        title="Document the retry policy",
        labels=["documentation"],
        body="The retry policy is undocumented.",
        comments=[],
    ),
]

ANALYSIS = RepoAnalysis(
    architecture_summary="A widget factory with a plugin system.",
    tech_stack=["Python", "FastAPI"],
    contribution_culture="Maintainers respond quickly and offer to review PRs directly.",
    issues=[
        IssueAnalysis(
            issue_id=1234,
            difficulty="moderate",
            skills=["Python", "asyncio"],
            summary="Add an asyncio-based client variant alongside the blocking one.",
            stale_or_claimed=False,
        ),
        IssueAnalysis(
            issue_id=1240,
            difficulty="trivial",
            skills=["technical writing"],
            summary="Write up the existing retry policy in the docs.",
            stale_or_claimed=False,
        ),
    ],
)


class FakeResponse:
    def __init__(self, *, stop_reason="end_turn", parsed_output=None, category=None):
        self.stop_reason = stop_reason
        self.parsed_output = parsed_output
        self.stop_details = type("Details", (), {"category": category})() if category else None


class FakeMessages:
    def __init__(self, response) -> None:
        self._response = response
        self.calls: list[dict] = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


class FakeClient:
    def __init__(self, response) -> None:
        self.messages = FakeMessages(response)


class TestModelChoice:
    def test_defaults_to_sonnet(self) -> None:
        """This step weighs conflicting signals across a whole repository's
        material, not single-field extraction, so it is not the tier Haiku
        is for.
        """
        assert MODEL == "claude-sonnet-5"

    def test_the_model_is_overridable(self) -> None:
        client = FakeClient(FakeResponse(parsed_output=ANALYSIS))
        ClaudeRepoAnalyzer(client=client, model="claude-opus-5").analyze(
            FACTS, None, None, ISSUE_MATERIAL
        )
        assert client.messages.calls[0]["model"] == "claude-opus-5"


class TestClientConstruction:
    def test_builds_its_own_client_when_none_is_given(self, monkeypatch) -> None:
        """The anthropic import is lazy so the package is importable, and the
        rest of the pipeline usable, without a key present.
        """
        import sys
        import types

        built: list[str] = []

        module = types.ModuleType("anthropic")
        module.Anthropic = lambda: built.append("constructed") or object()
        monkeypatch.setitem(sys.modules, "anthropic", module)

        ClaudeRepoAnalyzer()

        assert built == ["constructed"]


class TestAnalysis:
    def test_maps_the_parsed_analysis_onto_repo_intelligence(self) -> None:
        client = FakeClient(FakeResponse(parsed_output=ANALYSIS))
        intelligence = ClaudeRepoAnalyzer(client=client).analyze(FACTS, None, None, ISSUE_MATERIAL)

        assert isinstance(intelligence, RepoIntelligence)
        assert intelligence.repo_slug == "octo/widget"
        assert intelligence.architecture_summary == ANALYSIS.architecture_summary
        assert intelligence.tech_stack == ["Python", "FastAPI"]
        assert [i.issue_id for i in intelligence.issues] == [1234, 1240]
        assert intelligence.issues[0].difficulty == "moderate"
        assert intelligence.model_id == MODEL

    def test_sends_the_schema_and_the_system_prompt(self) -> None:
        client = FakeClient(FakeResponse(parsed_output=ANALYSIS))
        ClaudeRepoAnalyzer(client=client).analyze(
            FACTS, "a readme", "a contributing guide", ISSUE_MATERIAL
        )

        call = client.messages.calls[0]
        assert call["model"] == MODEL
        assert call["output_format"] is RepoAnalysis
        assert "a readme" in call["messages"][0]["content"]
        assert "a contributing guide" in call["messages"][0]["content"]
        assert "maintainer" in call["system"]


class TestFailurePaths:
    def test_a_refusal_is_reported_not_dereferenced(self) -> None:
        client = FakeClient(FakeResponse(stop_reason="refusal", category="cyber"))
        with pytest.raises(RepoAnalysisFailed) as excinfo:
            ClaudeRepoAnalyzer(client=client).analyze(FACTS, None, None, ISSUE_MATERIAL)

        assert "declined" in str(excinfo.value)
        assert "cyber" in str(excinfo.value)

    def test_a_refusal_without_a_category_still_reports(self) -> None:
        client = FakeClient(FakeResponse(stop_reason="refusal"))
        with pytest.raises(RepoAnalysisFailed, match="no category reported"):
            ClaudeRepoAnalyzer(client=client).analyze(FACTS, None, None, ISSUE_MATERIAL)

    def test_hitting_the_token_ceiling_names_the_limit(self) -> None:
        client = FakeClient(FakeResponse(stop_reason="max_tokens"))
        with pytest.raises(RepoAnalysisFailed) as excinfo:
            ClaudeRepoAnalyzer(client=client, max_tokens=1234).analyze(
                FACTS, None, None, ISSUE_MATERIAL
            )
        assert "1234" in str(excinfo.value)

    def test_a_missing_parsed_output_is_reported(self) -> None:
        client = FakeClient(FakeResponse(stop_reason="end_turn", parsed_output=None))
        with pytest.raises(RepoAnalysisFailed, match="no parsed analysis"):
            ClaudeRepoAnalyzer(client=client).analyze(FACTS, None, None, ISSUE_MATERIAL)

    def test_a_partial_result_is_reported_rather_than_silently_returned(self) -> None:
        """A consumer has no way to tell 'not analyzed' from 'analyzed,
        nothing notable', so covering only some candidate issues is a
        failure, not a smaller success.
        """
        incomplete = ANALYSIS.model_copy(update={"issues": ANALYSIS.issues[:1]})
        client = FakeClient(FakeResponse(parsed_output=incomplete))

        with pytest.raises(RepoAnalysisFailed, match="did not cover every candidate issue"):
            ClaudeRepoAnalyzer(client=client).analyze(FACTS, None, None, ISSUE_MATERIAL)

    def test_an_empty_issue_list_is_not_a_partial_result(self) -> None:
        """Zero candidates in, zero expected out - not a failure."""
        empty_analysis = ANALYSIS.model_copy(update={"issues": []})
        client = FakeClient(FakeResponse(parsed_output=empty_analysis))

        intelligence = ClaudeRepoAnalyzer(client=client).analyze(FACTS, None, None, [])
        assert intelligence.issues == []


class TestPromptAssembly:
    def test_includes_the_readme_and_contributing_text(self) -> None:
        prompt = _build_prompt(FACTS, "readme content", "contributing content", [])
        assert "readme content" in prompt
        assert "contributing content" in prompt

    def test_omits_the_root_files_line_when_there_are_none(self) -> None:
        empty = fixtures.repo_facts(root_files=[])
        prompt = _build_prompt(empty, None, None, [])
        assert "Root files" not in prompt

    def test_omits_sections_that_were_not_fetched(self) -> None:
        prompt = _build_prompt(FACTS, None, None, [])
        assert "## README" not in prompt
        assert "## CONTRIBUTING" not in prompt

    def test_lists_every_issue_with_its_body_and_comments(self) -> None:
        prompt = _build_prompt(FACTS, None, None, ISSUE_MATERIAL)
        assert "Issue #1234" in prompt
        assert "Issue #1240" in prompt
        assert "asyncio-based variant" in prompt
        assert "happy to review a PR" in prompt

    def test_says_so_when_there_are_no_candidate_issues(self) -> None:
        prompt = _build_prompt(FACTS, None, None, [])
        assert "No candidate issues were found" in prompt


class TestSchema:
    def test_the_sdk_sends_a_valid_structured_output_schema(self) -> None:
        from anthropic.lib._parse._transform import transform_schema

        sent = transform_schema(RepoAnalysis.model_json_schema())
        assert sent["additionalProperties"] is False
        assert sorted(sent["required"]) == sorted(RepoAnalysis.model_fields)

    def test_every_field_is_described(self) -> None:
        properties = RepoAnalysis.model_json_schema()["properties"]
        assert all("description" in prop for prop in properties.values())

        issue_properties = IssueAnalysis.model_json_schema()["properties"]
        assert all("description" in prop for prop in issue_properties.values())

    def test_difficulty_is_constrained_to_the_known_values(self) -> None:
        schema = IssueAnalysis.model_json_schema()
        assert set(schema["properties"]["difficulty"]["enum"]) == {
            "trivial",
            "easy",
            "moderate",
            "hard",
        }
