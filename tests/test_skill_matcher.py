"""Coverage for issue filtering, ranking, and the boost model."""

from datetime import UTC, datetime

import pytest

from pocket_oss_agent.agents.skill_matcher import (
    COLLAB_BOOST,
    LANGUAGE_BOOST,
    MINIMUM_SCORE,
    RISK_PENALTY,
    TYPE_BOOST,
    apply_hard_filters,
    build_rationale,
    drop_stale_or_claimed,
    is_confident,
    issue_text,
    match_issues,
    score_adjustments,
)
from pocket_oss_agent.embeddings import DeterministicEmbeddings
from pocket_oss_agent.errors import EmbeddingModelMismatch, MissingUpstreamOutput
from pocket_oss_agent.state import GoodFirstIssue, IssueIntelligence, RepoFacts, RepoIntelligence
from pocket_oss_agent.vector_store import InMemoryVectorStore

from . import fixtures


def intelligence(*issues: IssueIntelligence, repo_slug: str = "octo/widget") -> RepoIntelligence:
    return RepoIntelligence(
        repo_slug=repo_slug, issues=list(issues), computed_at=datetime(2026, 8, 16, tzinfo=UTC)
    )


def issue_intelligence(
    issue_id: int, *, stale: bool = False, summary: str = "s"
) -> IssueIntelligence:
    return IssueIntelligence(
        issue_id=issue_id, difficulty="easy", summary=summary, stale_or_claimed=stale
    )


def issue(n: int, title: str, *labels: str, comments: int = 0) -> GoodFirstIssue:
    return GoodFirstIssue(
        id=n,
        title=title,
        url=f"https://github.com/octo/widget/issues/{n}",
        labels=list(labels),
        days_open=3,
        comment_count=comments,
    )


def facts(*issues: GoodFirstIssue) -> RepoFacts:
    return fixtures.repo_facts(good_first_issues=list(issues))


EMBEDDINGS = DeterministicEmbeddings(dimensions=128)


class StubEmbeddings:
    """Returns vectors chosen by the test.

    Ranking is tested against exact similarities rather than whatever the
    hashing embedder happens to produce, so a threshold assertion means what it
    says. The first text is always the developer profile.
    """

    model_id = "stub"
    dimensions = 2

    def __init__(self, similarities: list[float]) -> None:
        #: cos(theta) against the profile vector [1, 0], one per issue.
        self._similarities = similarities

    def embed(self, texts: list[str]) -> list[list[float]]:
        import math

        vectors = [[1.0, 0.0]]
        for similarity in self._similarities[: len(texts) - 1]:
            angle = math.acos(max(-1.0, min(1.0, similarity)))
            vectors.append([math.cos(angle), math.sin(angle)])
        return vectors


class TestHardFilters:
    def test_keeps_only_the_requested_types(self) -> None:
        issues = [
            issue(1, "Fix crash", "bug"),
            issue(2, "Document retries", "documentation"),
            issue(3, "Add caching layer", "enhancement"),
        ]
        kept, filters = apply_hard_filters(
            issues, fixtures.interview_context(contribution_types=["bugfix"])
        )

        assert [i.id for i in kept] == [1]
        assert filters == ["contribution_types:bugfix"]

    def test_any_disables_filtering(self) -> None:
        issues = [issue(1, "Fix crash", "bug"), issue(2, "Add feature", "enhancement")]
        kept, filters = apply_hard_filters(
            issues, fixtures.interview_context(contribution_types=["any"])
        )

        assert len(kept) == 2
        assert filters == []

    def test_unlabelled_issues_survive(self) -> None:
        """Absent labels mean the repo does not use that vocabulary, not that
        the issue is unsuitable. Dropping them would empty most candidate sets.
        """
        issues = [issue(1, "Fix crash", "bug"), issue(2, "Something", "needs-triage")]
        kept, _ = apply_hard_filters(
            issues, fixtures.interview_context(contribution_types=["bugfix"])
        )

        assert [i.id for i in kept] == [1, 2]

    def test_multiple_types_union(self) -> None:
        issues = [
            issue(1, "Fix crash", "bug"),
            issue(2, "Docs", "documentation"),
            issue(3, "Feature", "enhancement"),
        ]
        kept, _ = apply_hard_filters(
            issues, fixtures.interview_context(contribution_types=["bugfix", "docs"])
        )

        assert [i.id for i in kept] == [1, 2]

    def test_unrecognised_contribution_types_disable_filtering(self) -> None:
        """A tag with no label mapping cannot express an intent, so filtering on
        it would silently discard every candidate.
        """
        issues = [issue(1, "Fix crash", "bug"), issue(2, "Docs", "documentation")]
        kept, filters = apply_hard_filters(
            issues, fixtures.interview_context(contribution_types=["telepathy"])
        )

        assert len(kept) == 2
        assert filters == []

    def test_label_matching_is_case_insensitive(self) -> None:
        kept, _ = apply_hard_filters(
            [issue(1, "Fix", "Bug")], fixtures.interview_context(contribution_types=["bugfix"])
        )
        assert len(kept) == 1


class TestScoreAdjustments:
    def test_language_boost_when_the_issue_mentions_a_top_language(self) -> None:
        adjustments = score_adjustments(
            issue(1, "Improve Python async client"),
            fixtures.developer_context(languages=["Python", "Go"]),
            fixtures.interview_context(),
        )
        assert adjustments["language_boost"] == LANGUAGE_BOOST

    def test_only_the_top_three_languages_count(self) -> None:
        developer = fixtures.developer_context(languages=["Go", "Rust", "Java", "Python"])
        adjustments = score_adjustments(
            issue(1, "Improve Python client"), developer, fixtures.interview_context()
        )
        assert adjustments["language_boost"] == 0.0

    def test_type_boost_on_a_matching_label(self) -> None:
        adjustments = score_adjustments(
            issue(1, "Fix crash", "bug"),
            fixtures.developer_context(),
            fixtures.interview_context(contribution_types=["bugfix"]),
        )
        assert adjustments["interview_type_boost"] == TYPE_BOOST

    def test_risk_penalty_only_for_low_tolerance(self) -> None:
        hard = issue(1, "Rewrite scheduler", "hard")
        low = score_adjustments(
            hard, fixtures.developer_context(), fixtures.interview_context(risk_tolerance="low")
        )
        high = score_adjustments(
            hard, fixtures.developer_context(), fixtures.interview_context(risk_tolerance="high")
        )

        assert low["risk_penalty"] == RISK_PENALTY
        assert high["risk_penalty"] == 0.0

    def test_collab_boost_needs_guided_and_enough_comments(self) -> None:
        guided = fixtures.interview_context(collaboration_style="guided")
        solo = fixtures.interview_context(collaboration_style="solo")

        assert (
            score_adjustments(issue(1, "x", comments=3), fixtures.developer_context(), guided)[
                "collab_boost"
            ]
            == COLLAB_BOOST
        )
        assert (
            score_adjustments(issue(1, "x", comments=2), fixtures.developer_context(), guided)[
                "collab_boost"
            ]
            == 0.0
        )
        assert (
            score_adjustments(issue(1, "x", comments=9), fixtures.developer_context(), solo)[
                "collab_boost"
            ]
            == 0.0
        )


class TestMatchIssues:
    def _match(self, repo, **overrides):
        return match_issues(
            overrides.get("developer", fixtures.developer_context()),
            overrides.get("interview", fixtures.interview_context()),
            repo,
            embeddings=overrides.get("embeddings", EMBEDDINGS),
            store=overrides.get("store"),
            repo_intelligence=overrides.get("repo_intelligence"),
        )

    @pytest.mark.parametrize("key", ["developer_context", "interview_context", "repo_facts"])
    def test_aborts_naming_the_missing_input(self, key: str) -> None:
        args = {
            "developer_context": fixtures.developer_context(),
            "interview_context": fixtures.interview_context(),
            "repo_facts": fixtures.repo_facts(),
        }
        args[key] = None

        with pytest.raises(MissingUpstreamOutput) as excinfo:
            match_issues(**args, embeddings=EMBEDDINGS)

        assert excinfo.value.key == key

    def test_returns_a_ranked_list_with_an_explainable_breakdown(self) -> None:
        repo = facts(
            issue(1, "Add Python asyncio client support", "bug", comments=5),
            issue(2, "Update the CSS on the docs site", "bug"),
        )
        top, filters, ranked = self._match(repo, embeddings=StubEmbeddings([0.7, 0.3]))

        assert top is not None
        assert top.issue_id == 1
        assert set(top.score_breakdown) == {
            "semantic_similarity",
            "language_boost",
            "interview_type_boost",
            "risk_penalty",
            "collab_boost",
        }
        assert top.score == pytest.approx(sum(top.score_breakdown.values()), abs=1e-4)
        assert "bugfix" in filters[0]
        assert len(ranked) == 2

    def test_no_candidates_after_filtering_yields_no_match(self) -> None:
        repo = facts(issue(1, "Add a feature", "enhancement"))
        top, _, ranked = self._match(
            repo, interview=fixtures.interview_context(contribution_types=["docs"])
        )

        assert top is None
        assert ranked == []

    def test_a_weak_best_match_is_reported_as_none(self) -> None:
        """`MINIMUM_SCORE` is a contractual null, not a failure: the roadmap
        renders a browse-manually section for it.
        """
        repo = facts(issue(1, "Bump the Rust toolchain in CI"))
        top, _, ranked = self._match(
            repo,
            developer=fixtures.developer_context(languages=["Haskell"], frameworks=[], tools=[]),
        )

        assert top is None
        assert ranked and ranked[0].score < MINIMUM_SCORE

    def test_an_empty_repo_yields_no_match(self) -> None:
        top, _, ranked = self._match(facts())
        assert (top, ranked) == (None, [])

    def test_results_are_capped(self) -> None:
        repo = facts(*[issue(n, f"Fix Python bug number {n}", "bug") for n in range(12)])
        _, _, ranked = self._match(repo)
        assert len(ranked) == 5

    def test_boosts_can_reorder_the_ranking(self) -> None:
        """A slightly less similar issue can win on the boost model, which is
        the whole point of keeping the two stages separate.
        """
        repo = facts(
            issue(1, "Refactor the scheduler internals", "bug"),
            issue(2, "Fix Python client retry logic", "bug", comments=5),
        )
        top, _, _ = self._match(
            repo,
            embeddings=StubEmbeddings([0.60, 0.55]),
            interview=fixtures.interview_context(collaboration_style="guided"),
        )

        assert top is not None
        assert top.issue_id == 2  # 0.55 + language + collab beats a bare 0.60

    def test_ranking_is_deterministic(self) -> None:
        repo = facts(
            issue(1, "Add Python asyncio client", "bug"),
            issue(2, "Fix Go module resolution", "bug"),
        )
        first = self._match(repo)[2]
        second = self._match(repo)[2]
        assert [m.issue_id for m in first] == [m.issue_id for m in second]

    def test_persists_issue_vectors_when_a_store_is_given(self) -> None:
        store = InMemoryVectorStore(model_id=EMBEDDINGS.model_id)
        repo = facts(issue(1, "Add Python client", "bug"), issue(2, "Fix docs", "bug"))

        self._match(repo, store=store)

        assert len(store) == 2

    def test_a_mismatched_store_aborts_before_embedding(self) -> None:
        store = InMemoryVectorStore(model_id="text-embedding-004")
        with pytest.raises(EmbeddingModelMismatch):
            self._match(facts(issue(1, "Fix", "bug")), store=store)


class TestDropStaleOrClaimed:
    def test_no_intelligence_keeps_everything(self) -> None:
        issues = [issue(1, "a"), issue(2, "b")]
        kept, filters = drop_stale_or_claimed(issues, None)
        assert kept == issues
        assert filters == []

    def test_removes_only_issues_marked_stale(self) -> None:
        issues = [issue(1, "a"), issue(2, "b")]
        repo_intel = intelligence(issue_intelligence(1, stale=True), issue_intelligence(2))

        kept, filters = drop_stale_or_claimed(issues, repo_intel)

        assert [i.id for i in kept] == [2]
        assert filters == ["repo_intelligence:stale_or_claimed"]

    def test_an_issue_intelligence_has_no_entry_for_is_kept(self) -> None:
        """Absence of a read is not evidence of staleness - a repo analyzed
        before this issue existed should not lose it.
        """
        issues = [issue(1, "a")]
        repo_intel = intelligence(issue_intelligence(999, stale=True))

        kept, filters = drop_stale_or_claimed(issues, repo_intel)

        assert [i.id for i in kept] == [1]
        assert filters == []

    def test_nothing_stale_reports_no_filter(self) -> None:
        issues = [issue(1, "a")]
        repo_intel = intelligence(issue_intelligence(1, stale=False))
        kept, filters = drop_stale_or_claimed(issues, repo_intel)
        assert kept == issues
        assert filters == []


class TestMatchIssuesWithRepoIntelligence:
    def _match(self, repo, repo_intelligence, **overrides):
        return match_issues(
            overrides.get("developer", fixtures.developer_context()),
            overrides.get("interview", fixtures.interview_context()),
            repo,
            embeddings=overrides.get("embeddings", EMBEDDINGS),
            repo_intelligence=repo_intelligence,
        )

    def test_a_stale_issue_never_reaches_the_ranking(self) -> None:
        repo = facts(issue(1, "Add Python asyncio client", "bug"), issue(2, "Fix docs", "bug"))
        repo_intel = intelligence(issue_intelligence(1, stale=True))

        _, filters, ranked = self._match(repo, repo_intel)

        assert 1 not in [m.issue_id for m in ranked]
        assert "repo_intelligence:stale_or_claimed" in filters

    def test_everything_stale_yields_no_match_rather_than_ranking_them_anyway(self) -> None:
        repo = facts(issue(1, "Add Python asyncio client", "bug"))
        repo_intel = intelligence(issue_intelligence(1, stale=True))

        top, _filters, ranked = self._match(repo, repo_intel)

        assert top is None
        assert ranked == []

    def test_the_rationale_uses_repo_analysts_summary_when_available(self) -> None:
        repo = facts(issue(1, "Add Python asyncio client", "bug"))
        repo_intel = intelligence(
            issue_intelligence(1, summary="Add an asyncio-based client variant.")
        )

        top, _filters, _ranked = self._match(repo, repo_intel, embeddings=StubEmbeddings([0.7]))

        assert top is not None
        assert "Add an asyncio-based client variant." in top.rationale

    def test_an_issue_repo_intelligence_does_not_cover_keeps_the_generic_rationale(self) -> None:
        repo = facts(issue(1, "Add Python asyncio client", "bug"))
        repo_intel = intelligence(issue_intelligence(999))

        top, _filters, _ranked = self._match(repo, repo_intel, embeddings=StubEmbeddings([0.7]))

        assert top is not None
        assert "Matches" in top.rationale


class TestRationale:
    def test_combines_a_resume_signal_and_an_interview_signal(self) -> None:
        rationale = build_rationale(
            issue(1, "Add async client"),
            fixtures.developer_context(languages=["Python"], years_experience=5),
            fixtures.interview_context(intent_summary="Developer wants to build their portfolio."),
        )

        assert rationale.startswith("You have 5 years of Python experience.")
        assert "developer wants to build their portfolio" in rationale
        assert rationale.count(".") == 2

    def test_degrades_without_years_or_languages(self) -> None:
        rationale = build_rationale(
            issue(1, "x"),
            fixtures.developer_context(languages=[], years_experience=None),
            fixtures.interview_context(intent_summary=""),
        )
        assert "You work in software." in rationale
        assert "your stated goal" in rationale

    def test_repo_analysts_summary_replaces_the_generic_interview_sentence(self) -> None:
        rationale = build_rationale(
            issue(1, "Add async client"),
            fixtures.developer_context(languages=["Python"], years_experience=5),
            fixtures.interview_context(intent_summary="Developer wants to build their portfolio."),
            issue_intelligence(1, summary="Add an asyncio-based client variant."),
        )

        assert (
            rationale
            == "You have 5 years of Python experience. Add an asyncio-based client variant."
        )
        assert "portfolio" not in rationale


class TestConfidence:
    @pytest.mark.parametrize(
        ("score", "expected"), [(None, False), (0.33, True), (0.32, False), (0.2, False)]
    )
    def test_threshold(self, score, expected) -> None:
        match = None if score is None else fixtures.top_match(score=score)
        assert is_confident(match) is expected


class TestIssueText:
    def test_embeds_title_and_labels(self) -> None:
        assert issue_text(issue(1, "Fix crash", "bug", "python")) == "Fix crash, bug, python"
