"""Coverage for roadmap assembly, including the spec's hard constraints."""

from datetime import UTC, datetime

import pytest

from pocket_oss_agent.agents.strategy_generator import (
    MAX_ROADMAP_LINES,
    generate_roadmap,
    verify_roadmap,
)
from pocket_oss_agent.errors import MissingUpstreamOutput
from pocket_oss_agent.state import GoodFirstIssue, IssueIntelligence, RepoIntelligence, SetupStep

from . import fixtures


def intelligence(**overrides) -> RepoIntelligence:
    defaults = dict(repo_slug="octo/widget", computed_at=datetime(2026, 8, 16, tzinfo=UTC))
    return RepoIntelligence(**{**defaults, **overrides})


def build(**overrides) -> str:
    defaults = dict(
        developer_context=fixtures.developer_context(),
        interview_context=fixtures.interview_context(),
        repo_facts=fixtures.repo_facts(),
        setup_steps=fixtures.setup_steps(),
        vibe_summary=fixtures.vibe_summary(),
        top_match=fixtures.top_match(),
    )
    return generate_roadmap(**{**defaults, **overrides})


class TestRequiredInputs:
    @pytest.mark.parametrize(
        "key",
        [
            "developer_context",
            "interview_context",
            "repo_facts",
            "setup_steps",
            "vibe_summary",
        ],
    )
    def test_aborts_naming_the_missing_key(self, key: str) -> None:
        with pytest.raises(MissingUpstreamOutput) as excinfo:
            build(**{key: None})

        assert excinfo.value.key == key
        assert key in str(excinfo.value)

    def test_top_match_is_the_one_permitted_null(self) -> None:
        roadmap = build(top_match=None)
        assert "## 🎯 Your First Contribution" in roadmap


class TestSpecConstraints:
    def test_a_complete_roadmap_passes_verification(self) -> None:
        assert verify_roadmap(build()) == []

    def test_stays_within_one_screen(self) -> None:
        assert len(build().splitlines()) <= MAX_ROADMAP_LINES

    def test_stays_within_budget_even_when_every_input_is_oversized(self) -> None:
        """The budget is a hard ceiling, not a typical case."""
        roadmap = build(
            repo_facts=fixtures.repo_facts(
                architecture_snapshot={f"dir{n}": f"Description {n}" for n in range(30)},
                good_first_issues=[
                    GoodFirstIssue(
                        id=n,
                        title=f"Issue {n} with a fairly long descriptive title",
                        url=f"https://github.com/octo/widget/issues/{n}",
                        days_open=n,
                        comment_count=n,
                    )
                    for n in range(40)
                ],
            ),
            setup_steps=fixtures.setup_steps(
                setup_steps=[
                    SetupStep(
                        step=n, command=f"run-step-{n} --with-a-long-flag", status="unverified"
                    )
                    for n in range(1, 41)
                ]
            ),
        )
        assert len(roadmap.splitlines()) <= MAX_ROADMAP_LINES
        assert verify_roadmap(roadmap) == []

    def test_never_drops_a_section_to_fit(self) -> None:
        roadmap = build(
            setup_steps=fixtures.setup_steps(
                setup_steps=[
                    SetupStep(step=n, command=f"step-{n}", status="unverified")
                    for n in range(1, 41)
                ]
            )
        )
        for heading in ("Architecture Snapshot", "First Mile Setup", "Your First Contribution"):
            assert heading in roadmap
        assert "…" in roadmap

    def test_every_link_is_https(self) -> None:
        assert "](https://" in build()
        assert verify_roadmap(build()) == []

    def test_header_carries_goal_and_availability(self) -> None:
        roadmap = build()
        assert "🎯 Goal: portfolio" in roadmap
        assert "⏱️ Availability: light (~5 hrs/week)" in roadmap

    def test_verifier_catches_a_malformed_document(self) -> None:
        problems = verify_roadmap("# Not a roadmap\n[link](http://insecure.example)")
        assert any("missing section" in p for p in problems)
        assert any("missing roadmap title" in p for p in problems)
        assert any("not an https URL" in p for p in problems)


class TestToneAdaptation:
    def test_low_risk_opens_with_reassurance(self) -> None:
        assert "close to what you already know" in build(
            interview_context=fixtures.interview_context(risk_tolerance="low")
        )

    def test_high_risk_skips_the_reassurance(self) -> None:
        assert "close to what you already know" not in build(
            interview_context=fixtures.interview_context(risk_tolerance="high")
        )

    def test_learning_goal_adds_a_learning_callout(self) -> None:
        assert "What you'll learn" in build(
            interview_context=fixtures.interview_context(goal="learning")
        )

    def test_career_goal_adds_a_job_search_callout(self) -> None:
        assert "How this helps" in build(
            interview_context=fixtures.interview_context(goal="career")
        )

    def test_light_availability_adds_time_estimates(self) -> None:
        roadmap = build(interview_context=fixtures.interview_context(time_commitment="light"))
        assert "~1 min" in roadmap
        assert "~3 min" in roadmap  # docker compose

    def test_heavier_availability_omits_estimates(self) -> None:
        roadmap = build(interview_context=fixtures.interview_context(time_commitment="heavy"))
        assert "~1 min" not in roadmap

    def test_at_least_one_adaptation_always_applies(self) -> None:
        for goal in ("learning", "portfolio", "professional", "career", "altruism"):
            for time in ("light", "moderate", "heavy"):
                for risk in ("low", "medium", "high"):
                    roadmap = build(
                        interview_context=fixtures.interview_context(
                            goal=goal, time_commitment=time, risk_tolerance=risk
                        )
                    )
                    assert verify_roadmap(roadmap) == []


class TestSections:
    def test_setup_marks_unverified_steps_and_says_why(self) -> None:
        roadmap = build()
        assert "⚠️" in roadmap
        assert "not yet executed" in roadmap

    def test_validated_steps_get_a_green_check(self) -> None:
        roadmap = build(
            setup_steps=fixtures.setup_steps(
                setup_steps=[
                    SetupStep(step=1, command="uv sync", status="validated"),
                    SetupStep(step=2, command="uv run pytest", status="validated"),
                ]
            )
        )
        assert "✅" in roadmap
        assert "not yet executed" not in roadmap

    def test_missing_architecture_says_so_rather_than_showing_nothing(self) -> None:
        """A monorepo detects no layout; silence would read as "no structure"."""
        roadmap = build(repo_facts=fixtures.repo_facts(architecture_snapshot={}))
        assert "not auto-detected" in roadmap

    def test_no_match_falls_back_to_browsable_issues(self) -> None:
        roadmap = build(top_match=None)
        assert "No strong match found" in roadmap
        assert "Document the retry policy" in roadmap

    def test_no_match_and_no_issues_still_gives_a_next_action(self) -> None:
        """Regression: the intro promised issues that the next line then said did
        not exist, reading as "these issues are open now: none".
        """
        roadmap = build(top_match=None, repo_facts=fixtures.repo_facts(good_first_issues=[]))
        assert "labels no beginner-friendly issues" in roadmap
        assert "are open now" not in roadmap
        assert "asking where to start" in roadmap
        assert verify_roadmap(roadmap) == []

    def test_low_merge_rate_is_explained_not_just_flagged(self) -> None:
        roadmap = build(vibe_summary=fixtures.vibe_summary(pr_merge_rate=0.06))
        assert "6% of closed PRs" in roadmap
        assert "Common for busy projects" in roadmap

    def test_healthy_merge_rate_adds_no_warning(self) -> None:
        assert "Common for busy projects" not in build(
            vibe_summary=fixtures.vibe_summary(pr_merge_rate=0.85)
        )

    def test_header_drops_the_greeting_without_a_name(self) -> None:
        roadmap = build(developer_context=fixtures.developer_context(name=None))
        assert "Generated for" not in roadmap
        assert verify_roadmap(roadmap) == []


class TestRepoIntelligence:
    """`repo_intelligence` is a nullable, cache-backed enrichment - every
    existing test above builds without it, so this covers what changes when
    it is present, not a parallel copy of the same assertions.
    """

    def test_architecture_summary_appears_alongside_the_bullets(self) -> None:
        roadmap = build(repo_intelligence=intelligence(architecture_summary="A widget factory."))
        assert "A widget factory." in roadmap
        assert "`src/` - Core library code" in roadmap

    def test_architecture_summary_stands_in_when_no_layout_was_detected(self) -> None:
        roadmap = build(
            repo_facts=fixtures.repo_facts(architecture_snapshot={}),
            repo_intelligence=intelligence(architecture_summary="A widget factory."),
        )
        assert "A widget factory." in roadmap
        assert "not auto-detected" not in roadmap

    def test_contribution_culture_is_set_off_from_the_quantitative_vibe_line(self) -> None:
        roadmap = build(
            repo_intelligence=intelligence(contribution_culture="Maintainers respond within a day.")
        )
        assert "_Maintainers respond within a day._" in roadmap

    def test_a_stale_issue_is_excluded_from_the_browse_manually_fallback(self) -> None:
        roadmap = build(
            top_match=None,
            repo_intelligence=intelligence(
                issues=[
                    IssueIntelligence(
                        issue_id=1234, difficulty="easy", summary="s", stale_or_claimed=True
                    )
                ]
            ),
        )
        assert "Add support for an async Python client" not in roadmap
        assert "Document the retry policy" in roadmap

    def test_every_candidate_stale_says_so_rather_than_claiming_none_exist(self) -> None:
        roadmap = build(
            top_match=None,
            repo_intelligence=intelligence(
                issues=[
                    IssueIntelligence(
                        issue_id=issue.id, difficulty="easy", summary="s", stale_or_claimed=True
                    )
                    for issue in fixtures.repo_facts().good_first_issues
                ]
            ),
        )
        assert "all looked already claimed" in roadmap
        assert "labels no beginner-friendly issues" not in roadmap
        assert verify_roadmap(roadmap) == []


class TestEdgeRendering:
    def test_name_without_a_profile_still_greets(self) -> None:
        roadmap = build(
            developer_context=fixtures.developer_context(name="Ada", seniority=None, domain=None)
        )
        assert "> Generated for Ada" in roadmap
        assert verify_roadmap(roadmap) == []

    def test_empty_setup_says_so_rather_than_showing_an_empty_list(self) -> None:
        roadmap = build(setup_steps=fixtures.setup_steps(setup_steps=[]))
        assert "No setup detected" in roadmap
        assert verify_roadmap(roadmap) == []

    def test_undetected_toolchain_is_called_out(self) -> None:
        """langchain nests its manifests, so the guide is clone and cd only."""
        roadmap = build(
            setup_steps=fixtures.setup_steps(
                package_manager=None,
                setup_steps=[
                    SetupStep(step=1, command="git clone https://x/y", status="unverified"),
                    SetupStep(step=2, command="cd y", status="unverified"),
                ],
            )
        )
        assert "No toolchain detected at the repo root" in roadmap
        assert "not yet executed" not in roadmap

    def test_line_budget_backstop_truncates_visibly(self) -> None:
        """Sections are individually capped, so this is a belt-and-braces path.
        Exercised directly because a silent overrun would break the one-screen
        promise the whole document is built around.
        """
        from pocket_oss_agent.agents.strategy_generator import _enforce_line_budget

        kept = _enforce_line_budget([f"line {n}" for n in range(200)])
        assert len(kept) == MAX_ROADMAP_LINES
        assert kept[-1].startswith("…")

    def test_verifier_reports_an_over_budget_document(self) -> None:
        oversized = build() + "\n" + "\n".join(f"pad {n}" for n in range(MAX_ROADMAP_LINES))
        assert any("exceeds" in p for p in verify_roadmap(oversized))

    def test_an_anonymous_profile_omits_the_byline_entirely(self) -> None:
        roadmap = build(
            developer_context=fixtures.developer_context(name=None, seniority=None, domain=None)
        )
        assert "Generated for" not in roadmap
        assert "engineer" not in roadmap
        assert verify_roadmap(roadmap) == []

    def test_advice_matches_the_diagnosis_for_a_quiet_repo(self) -> None:
        """Regression: a dormant repo with a 0% merge rate was told the project
        was "busy", sending the contributor to spend an evening on a PR nobody
        was going to look at.
        """
        roadmap = build(
            vibe_summary=fixtures.vibe_summary(
                pr_merge_rate=0.0, commit_status="potentially_dormant", commit_recency_days=172
            )
        )
        assert "Common for busy projects" not in roadmap
        assert "still taking contributions" in roadmap

    def test_active_repo_keeps_the_crowded_queue_reading(self) -> None:
        roadmap = build(
            vibe_summary=fixtures.vibe_summary(
                pr_merge_rate=0.06, commit_status="actively_maintained"
            )
        )
        assert "Common for busy projects" in roadmap
