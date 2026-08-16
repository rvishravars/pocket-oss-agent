"""Coverage for `repo-analyst`'s cache: the property that makes running the
analysis offline worth anything is that a hit skips computing it again.
"""

from datetime import UTC, datetime

from pocket_oss_agent.repo_intelligence_store import (
    FileRepoIntelligenceStore,
    InMemoryRepoIntelligenceStore,
)
from pocket_oss_agent.state import IssueIntelligence, RepoIntelligence

INTELLIGENCE = RepoIntelligence(
    repo_slug="octo/widget",
    architecture_summary="A widget factory with a plugin system.",
    tech_stack=["Python", "FastAPI"],
    contribution_culture="Maintainers respond within a day and give specific guidance.",
    issues=[
        IssueIntelligence(
            issue_id=7,
            difficulty="easy",
            skills=["Python"],
            summary="Fix the retry backoff calculation.",
            stale_or_claimed=False,
        )
    ],
    model_id="claude-sonnet-5",
    computed_at=datetime(2026, 8, 16, tzinfo=UTC),
)


class TestInMemoryRepoIntelligenceStore:
    def test_a_miss_returns_none(self) -> None:
        assert InMemoryRepoIntelligenceStore().get("octo/widget") is None

    def test_put_then_get_round_trips(self) -> None:
        store = InMemoryRepoIntelligenceStore()
        store.put(INTELLIGENCE)
        assert store.get("octo/widget") == INTELLIGENCE

    def test_a_second_put_for_the_same_slug_replaces_the_first(self) -> None:
        store = InMemoryRepoIntelligenceStore()
        store.put(INTELLIGENCE)
        updated = INTELLIGENCE.model_copy(update={"architecture_summary": "Rewritten."})
        store.put(updated)

        assert store.get("octo/widget").architecture_summary == "Rewritten."

    def test_different_slugs_do_not_collide(self) -> None:
        store = InMemoryRepoIntelligenceStore()
        store.put(INTELLIGENCE)
        assert store.get("octo/other") is None


class TestFileRepoIntelligenceStore:
    def test_a_miss_returns_none(self, tmp_path) -> None:
        assert FileRepoIntelligenceStore(tmp_path).get("octo/widget") is None

    def test_put_then_get_round_trips(self, tmp_path) -> None:
        store = FileRepoIntelligenceStore(tmp_path)
        store.put(INTELLIGENCE)
        assert store.get("octo/widget") == INTELLIGENCE

    def test_survives_a_fresh_store_instance(self, tmp_path) -> None:
        """The whole point of the file backend: it outlives the process."""
        FileRepoIntelligenceStore(tmp_path).put(INTELLIGENCE)
        reloaded = FileRepoIntelligenceStore(tmp_path).get("octo/widget")
        assert reloaded == INTELLIGENCE

    def test_the_repo_slug_slash_is_not_written_into_a_path_segment(self, tmp_path) -> None:
        store = FileRepoIntelligenceStore(tmp_path)
        store.put(INTELLIGENCE)

        files = list(tmp_path.iterdir())
        assert len(files) == 1
        assert "/" not in files[0].name

    def test_creates_the_directory_if_missing(self, tmp_path) -> None:
        target = tmp_path / "nested" / "cache"
        store = FileRepoIntelligenceStore(target)
        store.put(INTELLIGENCE)
        assert store.get("octo/widget") == INTELLIGENCE
