"""Unit coverage for the pure reduction logic in the investigator."""

from datetime import UTC, datetime, timedelta

import pytest

from pocket_oss_agent.agents.repo_investigator import (
    average_merge_days,
    build_architecture_snapshot,
    is_slow_moving,
    parse_repo_url,
    triage_issues,
)
from pocket_oss_agent.errors import InvalidRepoURL

NOW = datetime(2026, 8, 15, tzinfo=UTC)


def iso(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat().replace("+00:00", "Z")


class TestParseRepoURL:
    @pytest.mark.parametrize(
        "url",
        [
            "https://github.com/langchain-ai/langchain",
            "http://github.com/langchain-ai/langchain",
            "https://www.github.com/langchain-ai/langchain",
            "https://github.com/langchain-ai/langchain/",
            "https://github.com/langchain-ai/langchain.git",
            "github.com/langchain-ai/langchain",
            "git@github.com:langchain-ai/langchain.git",
            "langchain-ai/langchain",
            "  https://github.com/langchain-ai/langchain  ",
        ],
    )
    def test_accepts_the_forms_users_paste(self, url: str) -> None:
        assert parse_repo_url(url) == ("langchain-ai", "langchain")

    def test_preserves_dots_and_underscores_in_repo_names(self) -> None:
        assert parse_repo_url("https://github.com/psf/requests.mock_v2") == (
            "psf",
            "requests.mock_v2",
        )

    @pytest.mark.parametrize(
        "url", ["", "   ", "https://github.com/", "not a url", "https://gitlab.com/a/b/c/d"]
    )
    def test_rejects_unparseable_input(self, url: str) -> None:
        with pytest.raises(InvalidRepoURL):
            parse_repo_url(url)

    def test_error_names_the_offending_value(self) -> None:
        with pytest.raises(InvalidRepoURL, match="nonsense"):
            parse_repo_url("nonsense")


class TestArchitectureSnapshot:
    def test_keeps_only_recognised_top_level_directories(self) -> None:
        tree = [
            {"path": "src", "type": "tree"},
            {"path": "tests", "type": "tree"},
            {"path": "docs", "type": "tree"},
            {"path": "node_modules", "type": "tree"},
            {"path": "README.md", "type": "blob"},
        ]
        snapshot = build_architecture_snapshot(tree)
        assert set(snapshot) == {"src", "tests", "docs"}
        assert snapshot["src"] == "Core library code"

    def test_ignores_nested_paths(self) -> None:
        tree = [
            {"path": "packages/core/src", "type": "tree"},
            {"path": "src", "type": "tree"},
        ]
        assert set(build_architecture_snapshot(tree)) == {"src"}

    def test_discards_blobs_that_share_a_known_name(self) -> None:
        assert build_architecture_snapshot([{"path": "docs", "type": "blob"}]) == {}

    def test_empty_tree_yields_empty_snapshot(self) -> None:
        assert build_architecture_snapshot([]) == {}


class TestTriageIssues:
    def test_drops_pull_requests(self) -> None:
        issues = [
            {
                "number": 1,
                "title": "A PR",
                "html_url": "u",
                "created_at": iso(2),
                "updated_at": iso(1),
                "comments": 0,
                "pull_request": {"url": "..."},
            },
            {
                "number": 2,
                "title": "An issue",
                "html_url": "u",
                "created_at": iso(2),
                "updated_at": iso(1),
                "comments": 0,
            },
        ]
        assert [i.id for i in triage_issues(issues, now=NOW)] == [2]

    def test_drops_issues_untouched_beyond_the_activity_window(self) -> None:
        issues = [
            {
                "number": 1,
                "title": "stale",
                "html_url": "u",
                "created_at": iso(400),
                "updated_at": iso(120),
                "comments": 0,
            },
            {
                "number": 2,
                "title": "fresh",
                "html_url": "u",
                "created_at": iso(400),
                "updated_at": iso(10),
                "comments": 0,
            },
        ]
        assert [i.id for i in triage_issues(issues, now=NOW)] == [2]

    def test_caps_at_ten_newest_first(self) -> None:
        issues = [
            {
                "number": n,
                "title": f"issue {n}",
                "html_url": "u",
                "created_at": iso(n),
                "updated_at": iso(1),
                "comments": 0,
            }
            for n in range(1, 21)
        ]
        triaged = triage_issues(issues, now=NOW)
        assert len(triaged) == 10
        assert [i.days_open for i in triaged] == list(range(1, 11))

    def test_extracts_labels_and_comment_count(self) -> None:
        issues = [
            {
                "number": 7,
                "title": "Add async client",
                "html_url": "https://github.com/o/r/issues/7",
                "created_at": iso(5),
                "updated_at": iso(1),
                "comments": 4,
                "labels": [{"name": "good first issue"}, {"name": "python"}],
            }
        ]
        issue = triage_issues(issues, now=NOW)[0]
        assert issue.labels == ["good first issue", "python"]
        assert issue.comment_count == 4
        assert issue.days_open == 5

    def test_skips_records_with_unusable_timestamps(self) -> None:
        issues = [
            {"number": 1, "title": "x", "html_url": "u", "comments": 0},
            {
                "number": 2,
                "title": "y",
                "html_url": "u",
                "created_at": "garbage",
                "updated_at": iso(1),
                "comments": 0,
            },
        ]
        assert triage_issues(issues, now=NOW) == []

    def test_never_carries_the_issue_body(self) -> None:
        """The token budget forbids full issue bodies reaching RepoFacts."""
        issues = [
            {
                "number": 1,
                "title": "t",
                "html_url": "u",
                "created_at": iso(1),
                "updated_at": iso(1),
                "comments": 0,
                "body": "x" * 50_000,
            }
        ]
        issue = triage_issues(issues, now=NOW)[0]
        assert "body" not in issue.model_dump()


class TestAverageMergeDays:
    def test_averages_only_merged_pulls(self) -> None:
        pulls = [
            {"created_at": iso(10), "merged_at": iso(8)},  # 2 days
            {"created_at": iso(10), "merged_at": iso(6)},  # 4 days
            {"created_at": iso(10), "merged_at": None},  # closed unmerged
        ]
        assert average_merge_days(pulls) == 3.0

    def test_returns_none_when_nothing_merged(self) -> None:
        assert average_merge_days([{"created_at": iso(3), "merged_at": None}]) is None
        assert average_merge_days([]) is None

    def test_considers_at_most_twenty_pulls(self) -> None:
        pulls = [{"created_at": iso(10), "merged_at": iso(8)} for _ in range(20)]
        pulls += [{"created_at": iso(400), "merged_at": iso(10)} for _ in range(5)]
        assert average_merge_days(pulls) == 2.0

    @pytest.mark.parametrize(
        ("value", "expected"), [(None, False), (4.2, False), (30.0, False), (31.0, True)]
    )
    def test_slow_moving_threshold(self, value: float | None, expected: bool) -> None:
        assert is_slow_moving(value) is expected
