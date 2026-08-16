"""The session-state contract, including the fail-loudly rule from AGENTS.md."""

from datetime import UTC, datetime

import pytest

from pocket_oss_agent.errors import MissingUpstreamOutput
from pocket_oss_agent.state import IssueIntelligence, RepoFacts, RepoIntelligence, SessionState


def test_require_returns_a_present_value() -> None:
    facts = RepoFacts(owner="octo", repo="widget")
    state = SessionState(user_id="u1", repo_facts=facts)
    assert state.require("env-setup-validator", "repo_facts") is facts


def test_require_aborts_naming_the_agent_and_key() -> None:
    state = SessionState(user_id="u1")
    with pytest.raises(MissingUpstreamOutput) as excinfo:
        state.require("env-setup-validator", "repo_facts")

    message = str(excinfo.value)
    assert "env-setup-validator" in message
    assert "repo_facts" in message
    assert excinfo.value.key == "repo_facts"


def test_state_starts_empty_apart_from_the_user() -> None:
    state = SessionState(user_id="u1")
    for key in (
        "developer_context",
        "interview_context",
        "repo_facts",
        "repo_intelligence",
        "vibe_summary",
        "setup_steps",
        "top_match",
        "roadmap",
    ):
        assert getattr(state, key) is None


def test_repo_facts_round_trip_through_json() -> None:
    facts = RepoFacts(
        owner="octo",
        repo="widget",
        architecture_snapshot={"src": "Core library code"},
        avg_pr_merge_days=3.0,
    )
    assert RepoFacts.model_validate_json(facts.model_dump_json()) == facts


class TestStaleIssueIds:
    def _issue(self, issue_id: int, *, stale: bool) -> IssueIntelligence:
        return IssueIntelligence(
            issue_id=issue_id,
            difficulty="easy",
            summary="s",
            stale_or_claimed=stale,
        )

    def _intelligence(self, issues: list[IssueIntelligence]) -> RepoIntelligence:
        return RepoIntelligence(
            repo_slug="octo/widget",
            issues=issues,
            computed_at=datetime(2026, 8, 16, tzinfo=UTC),
        )

    def test_collects_only_the_ones_marked_stale(self) -> None:
        intelligence = self._intelligence([self._issue(1, stale=True), self._issue(2, stale=False)])
        assert intelligence.stale_issue_ids == {1}

    def test_empty_when_nothing_is_stale(self) -> None:
        intelligence = self._intelligence([self._issue(1, stale=False)])
        assert intelligence.stale_issue_ids == set()
