"""The session-state contract, including the fail-loudly rule from AGENTS.md."""

import pytest

from pocket_oss_agent.errors import MissingUpstreamOutput
from pocket_oss_agent.state import RepoFacts, SessionState


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
