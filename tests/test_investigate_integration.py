"""End-to-end coverage of `investigate` against mocked GitHub responses.

Uses respx so the real `GitHubClient` request path is exercised, including its
error mapping. No network access, so CI stays deterministic and offline.
"""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx

from pocket_oss_agent.agents.repo_investigator import TRIAGE_LABELS, investigate
from pocket_oss_agent.errors import InvalidRepoURL, RateLimited, RepositoryUnavailable
from pocket_oss_agent.github_client import API_ROOT, GitHubClient

NOW = datetime(2026, 8, 15, tzinfo=UTC)
REPO = "octo/widget"


def iso(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat().replace("+00:00", "Z")


TREE = {
    "tree": [
        {"path": "src", "type": "tree"},
        {"path": "tests", "type": "tree"},
        {"path": "docs", "type": "tree"},
        {"path": ".github", "type": "tree"},
        {"path": "src/widget/core.py", "type": "blob"},
    ]
}

ISSUES = [
    {
        "number": 41,
        "title": "Document the retry policy",
        "html_url": f"https://github.com/{REPO}/issues/41",
        "created_at": iso(6),
        "updated_at": iso(2),
        "comments": 3,
        "labels": [{"name": "good first issue"}, {"name": "documentation"}],
        "body": "long body " * 2000,
    },
    {
        "number": 42,
        "title": "A pull request",
        "html_url": f"https://github.com/{REPO}/pull/42",
        "created_at": iso(3),
        "updated_at": iso(1),
        "comments": 0,
        "labels": [],
        "pull_request": {"url": "..."},
    },
    {
        "number": 43,
        "title": "Abandoned request",
        "html_url": f"https://github.com/{REPO}/issues/43",
        "created_at": iso(500),
        "updated_at": iso(200),
        "comments": 1,
        "labels": [{"name": "help wanted"}],
    },
]

PULLS = [
    {"number": 1, "created_at": iso(20), "merged_at": iso(18)},
    {"number": 2, "created_at": iso(15), "merged_at": iso(11)},
    {"number": 3, "created_at": iso(9), "merged_at": None},
]


def mock_github(
    *, tree=TREE, issues=None, pulls=None, tree_status=200, headers=None, by_label=None
) -> respx.MockRouter:
    """Mock the three endpoints the investigator calls.

    `by_label` maps a single label to the issues returned for it, so tests can
    prove the union is assembled from separate per-label requests. GitHub's
    `labels` parameter is conjunctive, so a single combined query is wrong.
    """
    router = respx.mock(base_url=API_ROOT, assert_all_called=False)
    router.get(f"/repos/{REPO}/git/trees/HEAD").mock(
        return_value=httpx.Response(tree_status, json=tree, headers=headers or {})
    )

    if by_label is not None:

        def issues_responder(request: httpx.Request) -> httpx.Response:
            label = request.url.params.get("labels", "")
            return httpx.Response(200, json=by_label.get(label, []))

        router.get(f"/repos/{REPO}/issues").mock(side_effect=issues_responder)
    else:
        router.get(f"/repos/{REPO}/issues").mock(
            return_value=httpx.Response(200, json=ISSUES if issues is None else issues)
        )

    router.get(f"/repos/{REPO}/pulls").mock(
        return_value=httpx.Response(200, json=PULLS if pulls is None else pulls)
    )
    return router


def issue(number: int, *, labels: list[str], days_open: float = 5) -> dict:
    return {
        "number": number,
        "title": f"Issue {number}",
        "html_url": f"https://github.com/{REPO}/issues/{number}",
        "created_at": iso(days_open),
        "updated_at": iso(1),
        "comments": 0,
        "labels": [{"name": name} for name in labels],
    }


@pytest.fixture
async def client():
    async with GitHubClient(token="test-token") as c:
        yield c


async def test_builds_a_complete_fact_sheet(client: GitHubClient) -> None:
    with mock_github():
        facts = await investigate(f"https://github.com/{REPO}", client, now=NOW)

    assert (facts.owner, facts.repo) == ("octo", "widget")
    assert facts.slug == REPO
    assert set(facts.architecture_snapshot) == {"src", "tests", "docs"}
    assert facts.avg_pr_merge_days == 3.0

    assert [i.id for i in facts.good_first_issues] == [41]
    issue = facts.good_first_issues[0]
    assert issue.comment_count == 3
    assert issue.days_open == 6
    assert "documentation" in issue.labels


async def test_deferred_llm_summaries_stay_unset(client: GitHubClient) -> None:
    """Step 2 of the spec is not implemented yet and must not be faked."""
    with mock_github():
        facts = await investigate(f"https://github.com/{REPO}", client, now=NOW)

    assert facts.readme_summary is None
    assert facts.contributing_summary is None


async def test_serialized_facts_stay_small(client: GitHubClient) -> None:
    """The token budget forbids raw trees and issue bodies in RepoFacts."""
    with mock_github():
        facts = await investigate(f"https://github.com/{REPO}", client, now=NOW)

    payload = facts.model_dump_json()
    assert "long body" not in payload
    assert "src/widget/core.py" not in payload
    assert len(payload) < 2000


async def test_empty_repository_yields_empty_sections(client: GitHubClient) -> None:
    with mock_github(tree={"tree": []}, issues=[], pulls=[]):
        facts = await investigate(f"https://github.com/{REPO}", client, now=NOW)

    assert facts.architecture_snapshot == {}
    assert facts.good_first_issues == []
    assert facts.avg_pr_merge_days is None


async def test_private_or_missing_repository_aborts(client: GitHubClient) -> None:
    with mock_github(tree_status=404), pytest.raises(RepositoryUnavailable, match="octo/widget"):
        await investigate(f"https://github.com/{REPO}", client, now=NOW)


async def test_rate_limit_aborts_with_reset_time(client: GitHubClient) -> None:
    headers = {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1786000000"}
    with mock_github(tree_status=403, headers=headers), pytest.raises(RateLimited) as excinfo:
        await investigate(f"https://github.com/{REPO}", client, now=NOW)

    assert excinfo.value.reset_epoch == 1786000000


class TestLabelUnion:
    """GitHub's `labels` parameter is conjunctive, so triage labels must be
    requested one at a time and unioned. A single combined query returns only
    issues carrying every label, which is almost never any issue.
    """

    async def test_requests_each_triage_label_separately(self, client: GitHubClient) -> None:
        with mock_github(by_label={}) as router:
            await investigate(f"https://github.com/{REPO}", client, now=NOW)

            # respx clears its call log on context exit, so assert inside.
            issue_calls = [c for c in router.calls if "/issues" in c.request.url.path]
            requested = sorted(c.request.url.params["labels"] for c in issue_calls)

        assert requested == sorted(TRIAGE_LABELS)
        for label in requested:
            assert "," not in label, "labels must be requested one per call, not combined"

    async def test_unions_results_across_labels(self, client: GitHubClient) -> None:
        by_label = {
            "good first issue": [issue(1, labels=["good first issue"])],
            "help wanted": [issue(2, labels=["help wanted"])],
            "beginner": [issue(3, labels=["beginner"])],
        }
        with mock_github(by_label=by_label):
            facts = await investigate(f"https://github.com/{REPO}", client, now=NOW)

        assert sorted(i.id for i in facts.good_first_issues) == [1, 2, 3]

    async def test_deduplicates_an_issue_carrying_several_labels(
        self, client: GitHubClient
    ) -> None:
        shared = issue(9, labels=["good first issue", "help wanted"])
        by_label = {"good first issue": [shared], "help wanted": [shared], "beginner": []}
        with mock_github(by_label=by_label):
            facts = await investigate(f"https://github.com/{REPO}", client, now=NOW)

        assert [i.id for i in facts.good_first_issues] == [9]

    async def test_survives_a_label_with_no_matches(self, client: GitHubClient) -> None:
        by_label = {"help wanted": [issue(4, labels=["help wanted"])]}
        with mock_github(by_label=by_label):
            facts = await investigate(f"https://github.com/{REPO}", client, now=NOW)

        assert [i.id for i in facts.good_first_issues] == [4]


async def test_tree_is_fetched_non_recursively(client: GitHubClient) -> None:
    """A recursive fetch costs the whole file listing and is truncated on large
    repos, while only root entries are ever read.
    """
    with mock_github() as router:
        await investigate(f"https://github.com/{REPO}", client, now=NOW)
        tree_calls = [c for c in router.calls if "/git/trees/" in c.request.url.path]
        params = [dict(c.request.url.params) for c in tree_calls]

    assert len(params) == 1
    assert "recursive" not in params[0]


async def test_bad_url_fails_before_any_request(client: GitHubClient) -> None:
    with respx.mock(base_url=API_ROOT, assert_all_called=False) as router:
        with pytest.raises(InvalidRepoURL):
            await investigate("not a repo", client, now=NOW)
        assert not router.calls
