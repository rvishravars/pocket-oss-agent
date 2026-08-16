"""Direct coverage for the client's error and decoding paths.

Every agent sits on this class, so its failure modes are tested here rather
than only incidentally through whichever agent happens to call them.
"""

import base64

import httpx
import pytest
import respx

from pocket_oss_agent.errors import (
    NetworkUnavailable,
    PipelineError,
    RateLimited,
    RepositoryUnavailable,
)
from pocket_oss_agent.github_client import API_ROOT, GitHubClient

REPO = ("octo", "widget")


@pytest.fixture
async def client():
    async with GitHubClient(token="test-token") as c:
        yield c


def contents(text: str | None = None, *, encoding: str = "base64", size: int | None = None) -> dict:
    content = base64.b64encode(text.encode()).decode() if text is not None else ""
    return {
        "encoding": encoding,
        "content": content,
        "size": size if size is not None else len(text or ""),
    }


class TestAuth:
    async def test_sends_a_bearer_token_when_given_one(self) -> None:
        with respx.mock(base_url=API_ROOT) as router:
            route = router.get("/repos/octo/widget/commits").mock(
                return_value=httpx.Response(200, json=[])
            )
            async with GitHubClient(token="secret") as c:
                await c.list_commits(*REPO)
            assert route.calls.last.request.headers["Authorization"] == "Bearer secret"

    async def test_omits_authorization_without_a_token(self, monkeypatch) -> None:
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        with respx.mock(base_url=API_ROOT) as router:
            route = router.get("/repos/octo/widget/commits").mock(
                return_value=httpx.Response(200, json=[])
            )
            async with GitHubClient(token=None) as c:
                await c.list_commits(*REPO)
            assert "Authorization" not in route.calls.last.request.headers


class TestGetFileText:
    async def test_decodes_base64_content(self, client: GitHubClient) -> None:
        with respx.mock(base_url=API_ROOT) as router:
            router.get("/repos/octo/widget/contents/Makefile").mock(
                return_value=httpx.Response(200, json=contents("test:\n\tpytest\n"))
            )
            assert await client.get_file_text(*REPO, "Makefile") == "test:\n\tpytest\n"

    async def test_absent_file_is_none_not_an_error(self, client: GitHubClient) -> None:
        with respx.mock(base_url=API_ROOT) as router:
            router.get("/repos/octo/widget/contents/Makefile").mock(
                return_value=httpx.Response(404, json={"message": "Not Found"})
            )
            assert await client.get_file_text(*REPO, "Makefile") is None

    async def test_oversized_file_is_skipped(self, client: GitHubClient) -> None:
        """A caller parsing config wants to skip what it cannot read cheaply."""
        with respx.mock(base_url=API_ROOT) as router:
            router.get("/repos/octo/widget/contents/big.json").mock(
                return_value=httpx.Response(200, json=contents("x" * 100, size=5_000_000))
            )
            assert await client.get_file_text(*REPO, "big.json", max_bytes=1000) is None

    async def test_non_base64_encoding_is_skipped(self, client: GitHubClient) -> None:
        with respx.mock(base_url=API_ROOT) as router:
            router.get("/repos/octo/widget/contents/huge").mock(
                return_value=httpx.Response(200, json={"encoding": "none", "size": 1})
            )
            assert await client.get_file_text(*REPO, "huge") is None

    async def test_a_directory_listing_is_skipped(self, client: GitHubClient) -> None:
        """The contents endpoint returns a list for a directory, not a dict."""
        with respx.mock(base_url=API_ROOT) as router:
            router.get("/repos/octo/widget/contents/docker").mock(
                return_value=httpx.Response(200, json=[{"name": "a"}, {"name": "b"}])
            )
            assert await client.get_file_text(*REPO, "docker") is None

    async def test_undecodable_bytes_are_skipped(self, client: GitHubClient) -> None:
        payload = {
            "encoding": "base64",
            "content": base64.b64encode(b"\xff\xfe\x00binary").decode(),
            "size": 8,
        }
        with respx.mock(base_url=API_ROOT) as router:
            router.get("/repos/octo/widget/contents/logo.png").mock(
                return_value=httpx.Response(200, json=payload)
            )
            assert await client.get_file_text(*REPO, "logo.png") is None


class TestGetIssue:
    async def test_returns_the_full_record_including_the_body(self, client: GitHubClient) -> None:
        with respx.mock(base_url=API_ROOT) as router:
            router.get("/repos/octo/widget/issues/42").mock(
                return_value=httpx.Response(200, json={"number": 42, "body": "Steps to repro..."})
            )
            issue = await client.get_issue(*REPO, 42)
            assert issue == {"number": 42, "body": "Steps to repro..."}

    async def test_a_missing_issue_is_none_not_an_error(self, client: GitHubClient) -> None:
        with respx.mock(base_url=API_ROOT) as router:
            router.get("/repos/octo/widget/issues/999").mock(
                return_value=httpx.Response(404, json={"message": "Not Found"})
            )
            assert await client.get_issue(*REPO, 999) is None


class TestSearchCounts:
    async def test_returns_the_total(self, client: GitHubClient) -> None:
        with respx.mock(base_url=API_ROOT) as router:
            router.get("/search/issues").mock(
                return_value=httpx.Response(200, json={"total_count": 113, "items": []})
            )
            assert await client.count_matching_issues("repo:octo/widget is:pr") == 113

    async def test_missing_total_reads_as_zero(self, client: GitHubClient) -> None:
        with respx.mock(base_url=API_ROOT) as router:
            router.get("/search/issues").mock(return_value=httpx.Response(200, json={}))
            assert await client.count_matching_issues("q") == 0

    async def test_rate_limited_search_raises(self, client: GitHubClient) -> None:
        """Search has its own tighter quota, so this path is hit in practice."""
        with respx.mock(base_url=API_ROOT) as router:
            router.get("/search/issues").mock(
                return_value=httpx.Response(
                    403,
                    json={"message": "API rate limit exceeded"},
                    headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1786000000"},
                )
            )
            with pytest.raises(RateLimited) as excinfo:
                await client.count_matching_issues("q")
            assert excinfo.value.reset_epoch == 1786000000


class TestRateLimitDetection:
    async def test_detects_a_secondary_limit_from_the_body_alone(
        self, client: GitHubClient
    ) -> None:
        """Secondary limits arrive as a 403 without the remaining header."""
        with respx.mock(base_url=API_ROOT) as router:
            router.get("/repos/octo/widget/commits").mock(
                return_value=httpx.Response(
                    403, json={"message": "You have exceeded a secondary rate limit"}
                )
            )
            with pytest.raises(RateLimited):
                await client.list_commits(*REPO)

    async def test_a_plain_403_is_an_access_problem_not_a_limit(self, client: GitHubClient) -> None:
        with respx.mock(base_url=API_ROOT) as router:
            router.get("/repos/octo/widget/commits").mock(
                return_value=httpx.Response(403, json={"message": "Forbidden"})
            )
            with pytest.raises(RepositoryUnavailable):
                await client.list_commits(*REPO)

    async def test_unparseable_reset_header_does_not_crash(self, client: GitHubClient) -> None:
        with respx.mock(base_url=API_ROOT) as router:
            router.get("/repos/octo/widget/commits").mock(
                return_value=httpx.Response(
                    429,
                    json={"message": "rate limit"},
                    headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "soon"},
                )
            )
            with pytest.raises(RateLimited) as excinfo:
                await client.list_commits(*REPO)
            assert excinfo.value.reset_epoch is None


class TestTransportMapping:
    @pytest.mark.parametrize(
        "exc",
        [httpx.ConnectTimeout("t"), httpx.ReadTimeout("t"), httpx.ConnectError("dns")],
    )
    async def test_search_transport_failures_map_too(
        self, client: GitHubClient, exc: Exception
    ) -> None:
        """The search path builds its own request, so it needs the same mapping."""
        with respx.mock(base_url=API_ROOT) as router:
            router.get("/search/issues").mock(side_effect=exc)
            with pytest.raises(NetworkUnavailable) as excinfo:
                await client.count_matching_issues("q")
            assert isinstance(excinfo.value, PipelineError)


class TestListShapes:
    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("list_commits", "/repos/octo/widget/commits"),
            ("list_closed_pulls", "/repos/octo/widget/pulls"),
            ("list_recent_issues", "/repos/octo/widget/issues"),
        ],
    )
    async def test_unexpected_object_response_yields_an_empty_list(
        self, client: GitHubClient, method: str, path: str
    ) -> None:
        """GitHub returns an object for some error shapes; callers expect a list."""
        with respx.mock(base_url=API_ROOT) as router:
            router.get(path).mock(return_value=httpx.Response(200, json={"message": "odd"}))
            assert await getattr(client, method)(*REPO) == []

    async def test_tree_without_a_tree_key_yields_an_empty_list(self, client: GitHubClient) -> None:
        with respx.mock(base_url=API_ROOT) as router:
            router.get("/repos/octo/widget/git/trees/HEAD").mock(
                return_value=httpx.Response(200, json={})
            )
            assert await client.get_tree(*REPO) == []


class TestClientLifecycle:
    async def test_an_injected_transport_is_not_closed_by_the_wrapper(self) -> None:
        """The caller owns a client it supplied, so closing ours must not close
        theirs; otherwise one agent finishing tears down a shared pool.
        """
        transport = httpx.AsyncClient(base_url=API_ROOT)
        wrapper = GitHubClient(token="t", client=transport)

        await wrapper.aclose()
        assert not transport.is_closed

        await transport.aclose()
        assert transport.is_closed

    async def test_an_owned_transport_is_closed(self) -> None:
        wrapper = GitHubClient(token="t")
        await wrapper.aclose()
        assert wrapper._client.is_closed
