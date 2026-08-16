"""Coverage for `analyze_repo`'s gather-then-synthesize orchestration and cache.

Uses lightweight fake clients rather than respx, matching how `env-setup-validator`
is tested: this is agent-level orchestration, not the HTTP client's own request
shape, which `test_github_client.py` covers directly.
"""

from datetime import UTC, datetime

from pocket_oss_agent.agents.repo_analyst import analyze_repo
from pocket_oss_agent.repo_intelligence_store import InMemoryRepoIntelligenceStore
from pocket_oss_agent.state import IssueIntelligence, RepoIntelligence

from . import fixtures

FACTS = fixtures.repo_facts()  # root_files: Dockerfile, README.md, pyproject.toml, uv.lock

RESULT = RepoIntelligence(
    repo_slug="octo/widget",
    architecture_summary="A widget factory.",
    tech_stack=["Python"],
    contribution_culture="Responsive maintainers.",
    issues=[
        IssueIntelligence(
            issue_id=1234,
            difficulty="moderate",
            skills=["Python"],
            summary="s",
            stale_or_claimed=False,
        ),
        IssueIntelligence(
            issue_id=1240, difficulty="trivial", skills=[], summary="s", stale_or_claimed=False
        ),
    ],
    model_id="claude-sonnet-5",
    computed_at=datetime(2026, 8, 16, tzinfo=UTC),
)


class FakeAnalyzer:
    def __init__(self, result: RepoIntelligence = RESULT) -> None:
        self._result = result
        self.calls: list[tuple] = []

    def analyze(self, repo_facts, readme_text, contributing_text, issues):
        self.calls.append((repo_facts, readme_text, contributing_text, issues))
        return self._result


class FakeGitHubClient:
    def __init__(self, *, files=None, issues=None, comments=None) -> None:
        self._files = files or {}
        self._issues = issues or {}
        self._comments = comments or {}
        self.file_requests: list[str] = []
        self.issue_requests: list[int] = []
        self.comment_requests: list[int] = []

    async def get_file_text(self, owner, repo, path):
        self.file_requests.append(path)
        return self._files.get(path)

    async def get_issue(self, owner, repo, number):
        self.issue_requests.append(number)
        return self._issues.get(number)

    async def list_issue_comments(self, owner, repo, number, per_page=30):
        self.comment_requests.append(number)
        return self._comments.get(number, [])


class TestCache:
    async def test_a_hit_makes_no_github_or_claude_call(self) -> None:
        """The entire point of running offline: a popular repository is
        analyzed once, not once per contributor who asks about it.
        """
        store = InMemoryRepoIntelligenceStore()
        store.put(RESULT)
        client = FakeGitHubClient()
        analyzer = FakeAnalyzer()

        result = await analyze_repo(FACTS, client, analyzer, store)

        assert result == RESULT
        assert client.file_requests == []
        assert client.issue_requests == []
        assert analyzer.calls == []

    async def test_a_miss_computes_and_persists(self) -> None:
        store = InMemoryRepoIntelligenceStore()
        client = FakeGitHubClient(files={"README.md": "# Widget"})
        analyzer = FakeAnalyzer()

        result = await analyze_repo(FACTS, client, analyzer, store)

        assert result == RESULT
        assert store.get("octo/widget") == RESULT
        assert len(analyzer.calls) == 1


class TestDocumentGathering:
    async def test_fetches_only_the_readme_candidate_present_in_root_files(self) -> None:
        client = FakeGitHubClient(files={"README.md": "# Widget"})
        analyzer = FakeAnalyzer()

        await analyze_repo(FACTS, client, analyzer, InMemoryRepoIntelligenceStore())

        assert client.file_requests == ["README.md"]
        _, readme_text, contributing_text, _ = analyzer.calls[0]
        assert readme_text == "# Widget"
        assert contributing_text is None

    async def test_no_contributing_candidate_is_fetched_when_none_is_a_root_file(self) -> None:
        """FACTS has no CONTRIBUTING.md in root_files, so none of the
        candidate names should trigger a request.
        """
        client = FakeGitHubClient(files={"README.md": "# Widget", "CONTRIBUTING.md": "guide"})
        analyzer = FakeAnalyzer()

        await analyze_repo(FACTS, client, analyzer, InMemoryRepoIntelligenceStore())

        assert "CONTRIBUTING.md" not in client.file_requests

    async def test_a_missing_readme_file_is_passed_through_as_none(self) -> None:
        client = FakeGitHubClient(files={})
        analyzer = FakeAnalyzer()

        await analyze_repo(FACTS, client, analyzer, InMemoryRepoIntelligenceStore())

        _, readme_text, _, _ = analyzer.calls[0]
        assert readme_text is None


class TestIssueGathering:
    async def test_fetches_body_and_comments_for_every_candidate_issue(self) -> None:
        client = FakeGitHubClient(
            issues={
                1234: {"body": "The client blocks on every request."},
                1240: {"body": "The retry policy is undocumented."},
            },
            comments={1234: [{"body": "I can help with this."}], 1240: []},
        )
        analyzer = FakeAnalyzer()

        await analyze_repo(FACTS, client, analyzer, InMemoryRepoIntelligenceStore())

        assert sorted(client.issue_requests) == [1234, 1240]
        assert sorted(client.comment_requests) == [1234, 1240]

        _, _, _, issues = analyzer.calls[0]
        by_id = {issue.issue_id: issue for issue in issues}
        assert by_id[1234].body == "The client blocks on every request."
        assert by_id[1234].comments == ["I can help with this."]
        assert by_id[1240].comments == []

    async def test_a_missing_issue_body_is_an_empty_string_not_a_crash(self) -> None:
        client = FakeGitHubClient(issues={}, comments={})
        analyzer = FakeAnalyzer()

        await analyze_repo(FACTS, client, analyzer, InMemoryRepoIntelligenceStore())

        _, _, _, issues = analyzer.calls[0]
        assert all(issue.body == "" for issue in issues)

    async def test_comments_without_bodies_are_dropped(self) -> None:
        client = FakeGitHubClient(
            issues={1234: {}, 1240: {}},
            comments={1234: [{"body": "real"}, {"no_body": True}], 1240: []},
        )
        analyzer = FakeAnalyzer()

        await analyze_repo(FACTS, client, analyzer, InMemoryRepoIntelligenceStore())

        _, _, _, issues = analyzer.calls[0]
        by_id = {issue.issue_id: issue for issue in issues}
        assert by_id[1234].comments == ["real"]

    async def test_no_candidate_issues_means_no_issue_level_requests(self) -> None:
        empty_facts = fixtures.repo_facts(good_first_issues=[])
        client = FakeGitHubClient()
        analyzer = FakeAnalyzer()

        await analyze_repo(empty_facts, client, analyzer, InMemoryRepoIntelligenceStore())

        assert client.issue_requests == []
        assert client.comment_requests == []
        _, _, _, issues = analyzer.calls[0]
        assert issues == []


class TestTruncation:
    async def test_an_oversized_body_is_truncated(self) -> None:
        from pocket_oss_agent.agents.repo_analyst import MAX_BODY_CHARS

        client = FakeGitHubClient(issues={1234: {"body": "x" * (MAX_BODY_CHARS + 500)}, 1240: {}})
        analyzer = FakeAnalyzer()

        await analyze_repo(FACTS, client, analyzer, InMemoryRepoIntelligenceStore())

        _, _, _, issues = analyzer.calls[0]
        by_id = {issue.issue_id: issue for issue in issues}
        assert len(by_id[1234].body) == MAX_BODY_CHARS

    async def test_an_oversized_readme_is_truncated(self) -> None:
        from pocket_oss_agent.agents.repo_analyst import MAX_DOC_CHARS

        client = FakeGitHubClient(files={"README.md": "y" * (MAX_DOC_CHARS + 500)})
        analyzer = FakeAnalyzer()

        await analyze_repo(FACTS, client, analyzer, InMemoryRepoIntelligenceStore())

        _, readme_text, _, _ = analyzer.calls[0]
        assert len(readme_text) == MAX_DOC_CHARS
