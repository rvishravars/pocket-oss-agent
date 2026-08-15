"""End-to-end coverage of `check_vibe` against mocked GitHub responses."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx

from pocket_oss_agent.agents.vibe_checker import check_vibe
from pocket_oss_agent.errors import RateLimited, RepositoryUnavailable
from pocket_oss_agent.github_client import API_ROOT, GitHubClient
from pocket_oss_agent.state import GoodFirstIssue, RepoFacts

NOW = datetime(2026, 8, 15, tzinfo=UTC)
REPO = "octo/widget"


def iso(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat().replace("+00:00", "Z")


def facts(*, issues: int = 2) -> RepoFacts:
    return RepoFacts(
        owner="octo",
        repo="widget",
        good_first_issues=[
            GoodFirstIssue(id=n, title=f"i{n}", url="u", days_open=3, comment_count=1)
            for n in range(issues)
        ],
    )


COMMITS = [{"commit": {"committer": {"date": iso(2)}}}]

ISSUES = [
    {"number": 1, "created_at": iso(10), "comments": 2},
    {"number": 2, "created_at": iso(8), "comments": 1},
    {"number": 3, "created_at": iso(6), "comments": 0},  # no comments, not sampled
    {"number": 4, "created_at": iso(4), "comments": 5, "pull_request": {}},  # a PR
]

COMMENTS = {
    1: [{"created_at": iso(9), "author_association": "MEMBER"}],
    2: [{"created_at": iso(6), "author_association": "OWNER"}],
}

#: (merged, closed) totals the search endpoint reports for the window.
PR_COUNTS = (2, 3)

PROFILE = {
    "files": {
        "contributing": {"url": "..."},
        "code_of_conduct": {"url": "..."},
        "issue_template": {"url": "..."},
    }
}


def mock_github(
    *,
    commits=COMMITS,
    issues=ISSUES,
    pr_counts=PR_COUNTS,
    profile=PROFILE,
    profile_status=200,
    commits_status=200,
    headers=None,
) -> respx.MockRouter:
    router = respx.mock(base_url=API_ROOT, assert_all_called=False)
    router.get(f"/repos/{REPO}/commits").mock(
        return_value=httpx.Response(commits_status, json=commits, headers=headers or {})
    )
    router.get(f"/repos/{REPO}/issues").mock(return_value=httpx.Response(200, json=issues))

    def search_responder(request: httpx.Request) -> httpx.Response:
        merged, closed = pr_counts
        query = request.url.params.get("q", "")
        total = merged if "is:merged" in query else closed
        return httpx.Response(200, json={"total_count": total, "items": []})

    router.get("/search/issues").mock(side_effect=search_responder)
    router.get(f"/repos/{REPO}/community/profile").mock(
        return_value=httpx.Response(profile_status, json=profile)
    )

    def comments_responder(request: httpx.Request) -> httpx.Response:
        number = int(request.url.path.rstrip("/").split("/")[-2])
        return httpx.Response(200, json=COMMENTS.get(number, []))

    router.get(url__regex=rf".*/repos/{REPO}/issues/\d+/comments").mock(
        side_effect=comments_responder
    )
    return router


@pytest.fixture
async def client():
    async with GitHubClient(token="test-token") as c:
        yield c


async def test_produces_a_complete_report(client: GitHubClient) -> None:
    with mock_github():
        vibe = await check_vibe(facts(), client, now=NOW)

    assert vibe.commit_recency_days == 2
    assert vibe.commit_status == "actively_maintained"
    # issue 1 answered in 1 day, issue 2 in 2 days
    assert vibe.avg_issue_response_days == pytest.approx(1.5)
    assert vibe.response_status == "very_responsive"
    assert vibe.pr_merge_rate == pytest.approx(0.67)
    assert (vibe.welcome_score, vibe.welcome_rating) == (4, "welcoming")
    assert "actively maintained" in vibe.vibe_summary


async def test_samples_only_commented_issues_and_skips_pulls(client: GitHubClient) -> None:
    with mock_github() as router:
        await check_vibe(facts(), client, now=NOW)
        comment_calls = [c for c in router.calls if c.request.url.path.endswith("/comments")]
        numbers = sorted(int(c.request.url.path.split("/")[-2]) for c in comment_calls)

    assert numbers == [1, 2]


async def test_welcome_score_reuses_investigator_results(client: GitHubClient) -> None:
    """The good-first-issue signal comes from repo_facts, not a fresh query."""
    with mock_github():
        with_issues = await check_vibe(facts(issues=2), client, now=NOW)
        without_issues = await check_vibe(facts(issues=0), client, now=NOW)

    assert with_issues.welcome_score == 4
    assert without_issues.welcome_score == 3


async def test_missing_community_profile_degrades_rather_than_aborting(
    client: GitHubClient,
) -> None:
    with mock_github(profile_status=404, profile={}):
        vibe = await check_vibe(facts(), client, now=NOW)

    assert vibe.welcome_score == 1  # only the good-first-issue signal survives
    assert vibe.commit_status == "actively_maintained"


async def test_silent_repository_reports_unknowns(client: GitHubClient) -> None:
    with mock_github(commits=[], issues=[], pr_counts=(0, 0), profile={"files": {}}):
        vibe = await check_vibe(facts(issues=0), client, now=NOW)

    assert vibe.commit_status == "unknown"
    assert vibe.avg_issue_response_days is None
    assert vibe.response_status is None
    assert vibe.pr_merge_rate is None
    assert "could not be determined" in vibe.vibe_summary


async def test_private_repository_aborts(client: GitHubClient) -> None:
    with mock_github(commits_status=404), pytest.raises(RepositoryUnavailable):
        await check_vibe(facts(), client, now=NOW)


async def test_rate_limit_aborts_and_is_not_mistaken_for_a_missing_profile(
    client: GitHubClient,
) -> None:
    """A throttled community-profile call must raise, not score as absent."""
    router = respx.mock(base_url=API_ROOT, assert_all_called=False)
    router.get(f"/repos/{REPO}/commits").mock(return_value=httpx.Response(200, json=COMMITS))
    router.get(f"/repos/{REPO}/issues").mock(return_value=httpx.Response(200, json=[]))
    router.get("/search/issues").mock(return_value=httpx.Response(200, json={"total_count": 0}))
    router.get(f"/repos/{REPO}/community/profile").mock(
        return_value=httpx.Response(
            403,
            json={"message": "API rate limit exceeded"},
            headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1786000000"},
        )
    )

    with router, pytest.raises(RateLimited):
        await check_vibe(facts(), client, now=NOW)


async def test_issues_with_only_contributor_replies_yield_no_average(
    client: GitHubClient,
) -> None:
    """Sampled issues can all lack a maintainer reply. That is unmeasured, not
    instant, so the average must be None rather than zero.
    """
    issues = [{"number": 1, "created_at": iso(10), "comments": 3}]
    with mock_github(issues=issues) as router:
        router.get(url__regex=rf".*/repos/{REPO}/issues/\d+/comments").mock(
            return_value=httpx.Response(
                200, json=[{"created_at": iso(9), "author_association": "CONTRIBUTOR"}]
            )
        )
        vibe = await check_vibe(facts(), client, now=NOW)

    assert vibe.avg_issue_response_days is None
    assert vibe.response_status is None
    assert "no recent maintainer replies" in vibe.vibe_summary
