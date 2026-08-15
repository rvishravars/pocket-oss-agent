"""Coverage for the headless interview logic."""

import pytest

from pocket_oss_agent.agents.interviewer import (
    CATEGORIES,
    MAX_SUMMARY_WORDS,
    QUESTION_BANK,
    build_intent_summary,
    conduct_interview,
    opening_line,
)
from pocket_oss_agent.errors import (
    IncompleteInterview,
    MissingUpstreamOutput,
    UnknownInterviewAnswer,
)
from pocket_oss_agent.state import DeveloperContext

DEV = DeveloperContext(languages=["Python"], seniority="mid", domain="backend", years_experience=5)

COMPLETE = {
    "goal": "portfolio",
    "time_commitment": "light",
    "contribution_types": ["bugfix", "docs"],
    "risk_tolerance": "low",
    "collaboration_style": "guided",
}


class TestQuestionBank:
    def test_covers_the_five_specified_categories(self) -> None:
        assert [c.key for c in QUESTION_BANK] == [
            "goal",
            "time_commitment",
            "contribution_types",
            "risk_tolerance",
            "collaboration_style",
        ]

    def test_only_collaboration_style_is_optional(self) -> None:
        optional = [c.key for c in QUESTION_BANK if not c.required]
        assert optional == ["collaboration_style"]

    def test_only_contribution_types_allows_multiple(self) -> None:
        multi = [c.key for c in QUESTION_BANK if c.multi_select]
        assert multi == ["contribution_types"]

    def test_every_option_carries_a_renderable_label(self) -> None:
        for category in QUESTION_BANK:
            assert category.prompt.endswith("?")
            for option in category.options:
                assert option.label and option.value


class TestOpeningLine:
    def test_junior_gets_reassurance(self) -> None:
        line = opening_line(DeveloperContext(seniority="junior"))
        assert "no wrong answers" in line

    @pytest.mark.parametrize("seniority", ["senior", "staff"])
    def test_experienced_developers_get_the_terse_opening(self, seniority: str) -> None:
        line = opening_line(DeveloperContext(seniority=seniority))
        assert len(line.split()) < 12
        assert "no wrong answers" not in line

    def test_unknown_seniority_still_produces_an_opening(self) -> None:
        assert opening_line(DeveloperContext()).endswith("roadmap.")


class TestConductInterview:
    def test_maps_a_complete_set_of_answers(self) -> None:
        context = conduct_interview(DEV, COMPLETE)

        assert context.goal == "portfolio"
        assert context.time_commitment == "light"
        assert context.contribution_types == ["bugfix", "docs"]
        assert context.risk_tolerance == "low"
        assert context.collaboration_style == "guided"

    def test_optional_category_defaults_when_skipped(self) -> None:
        answers = {k: v for k, v in COMPLETE.items() if k != "collaboration_style"}
        assert conduct_interview(DEV, answers).collaboration_style == "any"

    @pytest.mark.parametrize(
        "missing_key", ["goal", "time_commitment", "contribution_types", "risk_tolerance"]
    )
    def test_missing_mandatory_answer_is_an_error_not_a_default(self, missing_key: str) -> None:
        """The spec requires re-prompting; these drive filtering and tone."""
        answers = {k: v for k, v in COMPLETE.items() if k != missing_key}
        with pytest.raises(IncompleteInterview) as excinfo:
            conduct_interview(DEV, answers)

        assert excinfo.value.missing == [missing_key]
        assert missing_key in str(excinfo.value)

    def test_reports_every_missing_category_at_once(self) -> None:
        with pytest.raises(IncompleteInterview) as excinfo:
            conduct_interview(DEV, {"goal": "portfolio"})

        assert excinfo.value.missing == [
            "contribution_types",
            "risk_tolerance",
            "time_commitment",
        ]

    @pytest.mark.parametrize("empty", [None, "", []])
    def test_blank_answers_count_as_missing(self, empty) -> None:
        answers = {**COMPLETE, "goal": empty}
        with pytest.raises(IncompleteInterview):
            conduct_interview(DEV, answers)

    def test_rejects_an_answer_outside_the_option_list(self) -> None:
        with pytest.raises(UnknownInterviewAnswer, match="fame"):
            conduct_interview(DEV, {**COMPLETE, "goal": "fame"})

    def test_rejects_an_invalid_entry_inside_a_multi_select(self) -> None:
        with pytest.raises(UnknownInterviewAnswer, match="telepathy"):
            conduct_interview(DEV, {**COMPLETE, "contribution_types": ["docs", "telepathy"]})

    def test_accepts_a_bare_value_for_a_multi_select(self) -> None:
        context = conduct_interview(DEV, {**COMPLETE, "contribution_types": "docs"})
        assert context.contribution_types == ["docs"]

    def test_requires_the_developer_context(self) -> None:
        with pytest.raises(MissingUpstreamOutput) as excinfo:
            conduct_interview(None, COMPLETE)

        assert excinfo.value.key == "developer_context"


class TestIntentSummary:
    def test_reads_like_the_specified_example(self) -> None:
        summary = build_intent_summary("portfolio", "light", ["bugfix"], "low")

        assert summary.startswith("Developer wants to build their portfolio")
        assert "bug fixes" in summary
        assert "~5 hrs/week" in summary
        assert "familiar territory" in summary
        assert summary.endswith(".")

    def test_stays_inside_the_word_budget_for_every_combination(self) -> None:
        goals = [o.value for o in CATEGORIES["goal"].options]
        times = [o.value for o in CATEGORIES["time_commitment"].options]
        risks = [o.value for o in CATEGORIES["risk_tolerance"].options]
        all_types = [o.value for o in CATEGORIES["contribution_types"].options]

        for goal in goals:
            for time in times:
                for risk in risks:
                    summary = build_intent_summary(goal, time, all_types, risk)
                    assert len(summary.split()) <= MAX_SUMMARY_WORDS, summary

    def test_elides_a_long_multi_select(self) -> None:
        summary = build_intent_summary(
            "learning", "heavy", ["bugfix", "docs", "tests", "refactor"], "high"
        )
        assert "and more" in summary

    def test_generated_summary_lands_on_the_context(self) -> None:
        context = conduct_interview(DEV, COMPLETE)
        assert context.intent_summary == build_intent_summary(
            "portfolio", "light", ["bugfix", "docs"], "low"
        )
        assert len(context.intent_summary.split()) <= MAX_SUMMARY_WORDS
