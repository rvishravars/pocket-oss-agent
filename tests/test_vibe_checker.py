"""Unit coverage for the vibe-check scoring logic."""

from datetime import UTC, datetime, timedelta

import pytest

from pocket_oss_agent.agents.vibe_checker import (
    commit_recency,
    compose_summary,
    first_maintainer_reply_days,
    is_healthy_merge_rate,
    is_high_rejection_risk,
    merge_rate_from_counts,
    merge_rate_queries,
    response_status,
    welcome_signals,
)

NOW = datetime(2026, 8, 15, tzinfo=UTC)


def iso(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat().replace("+00:00", "Z")


def commit(days_ago: float) -> dict:
    return {"commit": {"committer": {"date": iso(days_ago)}}}


class TestCommitRecency:
    @pytest.mark.parametrize(
        ("days_ago", "expected"),
        [
            (0, "actively_maintained"),
            (7, "actively_maintained"),
            (8, "moderate_activity"),
            (30, "moderate_activity"),
            (31, "slowing_down"),
            (90, "slowing_down"),
            (91, "potentially_dormant"),
            (900, "potentially_dormant"),
        ],
    )
    def test_thresholds_are_inclusive_at_each_boundary(self, days_ago, expected) -> None:
        days, status = commit_recency([commit(days_ago)], now=NOW)
        assert status == expected
        assert days == days_ago

    def test_uses_the_most_recent_commit_not_the_first_listed(self) -> None:
        days, status = commit_recency([commit(200), commit(3), commit(90)], now=NOW)
        assert (days, status) == (3, "actively_maintained")

    def test_no_commits_is_unresolved_rather_than_dormant(self) -> None:
        assert commit_recency([], now=NOW) == (None, None)

    def test_unparseable_dates_are_skipped(self) -> None:
        commits = [{"commit": {"committer": {"date": "nonsense"}}}, commit(5)]
        assert commit_recency(commits, now=NOW)[0] == 5


class TestResponseStatus:
    @pytest.mark.parametrize(
        ("avg", "expected"),
        [
            (0.5, "very_responsive"),
            (1.9, "very_responsive"),
            (2.0, "moderate"),
            (7.0, "moderate"),
            (7.1, "slow_to_respond"),
            (None, None),
        ],
    )
    def test_buckets(self, avg, expected) -> None:
        assert response_status(avg) == expected


class TestFirstMaintainerReply:
    def test_ignores_replies_from_non_maintainers(self) -> None:
        issue = {"created_at": iso(10)}
        comments = [
            {"created_at": iso(9), "author_association": "CONTRIBUTOR"},
            {"created_at": iso(8), "author_association": "NONE"},
            {"created_at": iso(6), "author_association": "MEMBER"},
        ]
        assert first_maintainer_reply_days(issue, comments) == pytest.approx(4.0)

    @pytest.mark.parametrize("association", ["OWNER", "MEMBER", "COLLABORATOR"])
    def test_write_access_associations_count(self, association: str) -> None:
        issue = {"created_at": iso(5)}
        comments = [{"created_at": iso(4), "author_association": association}]
        assert first_maintainer_reply_days(issue, comments) == pytest.approx(1.0)

    def test_returns_none_when_only_contributors_replied(self) -> None:
        issue = {"created_at": iso(5)}
        comments = [{"created_at": iso(4), "author_association": "CONTRIBUTOR"}]
        assert first_maintainer_reply_days(issue, comments) is None

    def test_returns_none_without_comments(self) -> None:
        assert first_maintainer_reply_days({"created_at": iso(5)}, []) is None

    def test_takes_the_earliest_maintainer_reply(self) -> None:
        issue = {"created_at": iso(10)}
        comments = [
            {"created_at": iso(2), "author_association": "OWNER"},
            {"created_at": iso(9), "author_association": "OWNER"},
        ]
        assert first_maintainer_reply_days(issue, comments) == pytest.approx(1.0)

    def test_ignores_comments_predating_the_issue(self) -> None:
        """Guards against a negative response time from clock skew or bad data."""
        issue = {"created_at": iso(5)}
        comments = [{"created_at": iso(9), "author_association": "OWNER"}]
        assert first_maintainer_reply_days(issue, comments) is None


class TestPRMergeRate:
    @pytest.mark.parametrize(
        ("merged", "closed", "expected"),
        [(3, 50, 0.06), (24, 113, 0.21), (0, 10, 0.0), (10, 10, 1.0)],
    )
    def test_rate_from_exact_counts(self, merged: int, closed: int, expected: float) -> None:
        assert merge_rate_from_counts(merged, closed) == expected

    def test_returns_none_when_nothing_closed_in_the_window(self) -> None:
        assert merge_rate_from_counts(0, 0) is None

    def test_builds_a_window_bounded_search_pair(self) -> None:
        merged_q, closed_q = merge_rate_queries("octo", "widget", now=NOW)

        # NOW is 2026-08-15, so the 90 day window opens on 2026-05-17.
        assert merged_q == "repo:octo/widget is:pr closed:>=2026-05-17 is:merged"
        assert closed_q == "repo:octo/widget is:pr closed:>=2026-05-17 is:closed"

    @pytest.mark.parametrize(
        ("rate", "healthy", "risky"),
        [(None, False, False), (0.78, True, False), (0.60, False, True), (0.45, False, True)],
    )
    def test_derived_flags(self, rate, healthy, risky) -> None:
        assert is_healthy_merge_rate(rate) is healthy
        assert is_high_rejection_risk(rate) is risky


class TestWelcomeSignals:
    def test_full_marks(self) -> None:
        profile = {
            "files": {
                "contributing": {"url": "..."},
                "code_of_conduct": {"url": "..."},
                "issue_template": {"url": "..."},
            }
        }
        assert welcome_signals(profile, has_good_first_issues=True) == (4, "welcoming")

    def test_missing_profile_scores_only_the_issue_signal(self) -> None:
        assert welcome_signals(None, has_good_first_issues=True) == (1, "unfriendly")

    def test_null_file_entries_do_not_count(self) -> None:
        profile = {"files": {"contributing": None, "code_of_conduct": None, "issue_template": None}}
        assert welcome_signals(profile, has_good_first_issues=False) == (0, "unfriendly")

    @pytest.mark.parametrize(("score", "rating"), [(4, "welcoming"), (2, "moderate")])
    def test_rating_boundaries(self, score: int, rating: str) -> None:
        files = {
            key: ({"url": "..."} if i < score else None)
            for i, key in enumerate(("contributing", "code_of_conduct", "issue_template"))
        }
        has_gfi = score == 4
        assert welcome_signals({"files": files}, has_good_first_issues=has_gfi)[1] == rating


class TestComposeSummary:
    def test_reads_as_prose_with_every_signal_present(self) -> None:
        text = compose_summary(
            commit_days=2,
            commit_status="actively_maintained",
            avg_response_days=1.3,
            merge_rate=0.78,
            welcome_score=4,
            welcome_rating="welcoming",
            good_first_issue_count=12,
        )
        assert "actively maintained" in text
        assert "2 days ago" in text
        assert "1.3 days" in text
        assert "78%" in text
        assert "12 open beginner-friendly issues" in text
        assert text.count(".") >= 2

    def test_keeps_pr_capitalised_without_a_leading_issue_clause(self) -> None:
        """Regression: str.capitalize() lowercases the tail, giving "prs"."""
        text = compose_summary(
            commit_days=3,
            commit_status="actively_maintained",
            avg_response_days=0.4,
            merge_rate=0.07,
            welcome_score=2,
            welcome_rating="moderate",
            good_first_issue_count=0,  # no leading clause, so this one starts the sentence
        )
        assert "PRs" in text
        assert "prs" not in text

    def test_states_unknowns_instead_of_inventing_them(self) -> None:
        text = compose_summary(
            commit_days=None,
            commit_status=None,
            avg_response_days=None,
            merge_rate=None,
            welcome_score=0,
            welcome_rating="unfriendly",
            good_first_issue_count=0,
        )
        assert "could not be determined" in text
        assert "no recent maintainer replies" in text
        assert "0%" not in text
