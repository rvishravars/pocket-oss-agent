"""Storage for `repo-analyst`'s output, keyed by repository.

`RepoIntelligence` is computed once per repository and reused by every
subsequent request for it - the entire point of running the analysis offline
rather than per session. This module is the seam that makes that caching
swappable: `InMemoryRepoIntelligenceStore` for tests and a single process,
`FileRepoIntelligenceStore` for something that survives a restart without
standing up a database. A Postgres-backed store is future work, the same way
`PgVectorStore` followed `InMemoryVectorStore`; nothing here depends on it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from .state import RepoIntelligence


class RepoIntelligenceStore(Protocol):
    """Reads and writes one `RepoIntelligence` record per repository."""

    def get(self, repo_slug: str) -> RepoIntelligence | None: ...

    def put(self, intelligence: RepoIntelligence) -> None: ...


class InMemoryRepoIntelligenceStore:
    """A dict. Gone when the process exits, which is fine for tests and
    for local development that does not need the cache to survive a restart.
    """

    def __init__(self) -> None:
        self._records: dict[str, RepoIntelligence] = {}

    def get(self, repo_slug: str) -> RepoIntelligence | None:
        return self._records.get(repo_slug)

    def put(self, intelligence: RepoIntelligence) -> None:
        self._records[intelligence.repo_slug] = intelligence


class FileRepoIntelligenceStore:
    """One JSON file per repository under `directory`.

    Survives a restart without a database. The slug's `/` is not filesystem-
    safe, so it is replaced with `__` in the filename; `repo_slug` inside the
    stored record is the source of truth, the filename is just a cache key.
    """

    def __init__(self, directory: str | Path) -> None:
        self._directory = Path(directory)
        self._directory.mkdir(parents=True, exist_ok=True)

    def get(self, repo_slug: str) -> RepoIntelligence | None:
        path = self._path_for(repo_slug)
        if not path.exists():
            return None
        return RepoIntelligence.model_validate_json(path.read_text())

    def put(self, intelligence: RepoIntelligence) -> None:
        path = self._path_for(intelligence.repo_slug)
        path.write_text(intelligence.model_dump_json())

    def _path_for(self, repo_slug: str) -> Path:
        return self._directory / f"{repo_slug.replace('/', '__')}.json"
