"""Shared fixtures for the graph and API tests.

Both layers need a GitHub mock covering every endpoint the pipeline touches,
plus a fake extractor. Keeping them here means one place to update when an
agent starts calling something new.
"""

import httpx
import pytest
import respx

from pocket_oss_agent.embeddings import DeterministicEmbeddings
from pocket_oss_agent.github_client import API_ROOT, GitHubClient
from pocket_oss_agent.graph import Dependencies
from pocket_oss_agent.state import DeveloperContext

REPO = "octo/widget"
RESUME = "Ada Okafor. " + "Senior Python and Go backend engineer, FastAPI and Docker. " * 8


class FakeExtractor:
    """Stands in for the Claude call, so no test needs a key."""

    def __init__(self, context: DeveloperContext | None = None) -> None:
        self.context = context or DeveloperContext(
            name="Ada Okafor",
            languages=["Python", "Go"],
            frameworks=["FastAPI"],
            tools=["Docker", "AWS"],
            years_experience=6,
            seniority="senior",
            domain="backend",
        )
        self.calls: list[str] = []

    def extract(self, resume_text: str) -> DeveloperContext:
        self.calls.append(resume_text)
        return self.context


def github_routes(*, issues=None, tree=None) -> respx.MockRouter:
    """Every endpoint the pipeline calls, in one router."""
    router = respx.mock(base_url=API_ROOT, assert_all_called=False)
    router.get(f"/repos/{REPO}/git/trees/HEAD").mock(
        return_value=httpx.Response(
            200,
            json={
                "tree": tree
                or [
                    {"path": "src", "type": "tree"},
                    {"path": "tests", "type": "tree"},
                    {"path": "pyproject.toml", "type": "blob"},
                ]
            },
        )
    )
    router.get(f"/repos/{REPO}/issues").mock(
        return_value=httpx.Response(
            200,
            json=issues
            if issues is not None
            else [
                {
                    "number": 7,
                    "title": "Fix Python client retry logic",
                    "html_url": f"https://github.com/{REPO}/issues/7",
                    "created_at": "2026-08-10T00:00:00Z",
                    "updated_at": "2026-08-15T00:00:00Z",
                    "comments": 4,
                    "labels": [{"name": "bug"}],
                }
            ],
        )
    )
    router.get(f"/repos/{REPO}/pulls").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "number": 1,
                    "created_at": "2026-08-01T00:00:00Z",
                    "merged_at": "2026-08-03T00:00:00Z",
                    "closed_at": "2026-08-03T00:00:00Z",
                }
            ],
        )
    )
    router.get(f"/repos/{REPO}/commits").mock(
        return_value=httpx.Response(
            200, json=[{"commit": {"committer": {"date": "2026-08-15T00:00:00Z"}}}]
        )
    )
    router.get("/search/issues").mock(return_value=httpx.Response(200, json={"total_count": 1}))
    router.get(f"/repos/{REPO}/community/profile").mock(
        return_value=httpx.Response(200, json={"files": {"contributing": {"url": "x"}}})
    )
    router.get(url__regex=r".*/issues/\d+/comments").mock(
        return_value=httpx.Response(
            200, json=[{"created_at": "2026-08-11T00:00:00Z", "author_association": "OWNER"}]
        )
    )
    # Anchored so this does not also swallow the /comments route above: a
    # bare /issues/7 is repo-analyst's single-issue body fetch.
    router.get(url__regex=r".*/issues/\d+$").mock(
        return_value=httpx.Response(200, json={"number": 7, "body": "Fix the retry backoff."})
    )
    router.get(url__regex=r".*/contents/.*").mock(return_value=httpx.Response(404, json={}))
    return router


ANSWERS = {
    "goal": "portfolio",
    "time_commitment": "light",
    "contribution_types": ["bugfix"],
    "risk_tolerance": "low",
    "collaboration_style": "guided",
}


@pytest.fixture
async def github():
    async with GitHubClient(token="test-token") as client:
        yield client


@pytest.fixture
def extractor() -> FakeExtractor:
    return FakeExtractor()


@pytest.fixture
def deps(github, extractor) -> Dependencies:
    return Dependencies(
        extractor=extractor,
        embeddings=DeterministicEmbeddings(dimensions=64),
        github=github,
    )
