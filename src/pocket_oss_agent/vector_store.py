"""Vector storage behind one interface.

`InMemoryVectorStore` computes cosine similarity in Python. It is what the test
suite and local development use, and it is honest about its cost: fine for the
handful of candidate issues one roadmap considers, wrong for a corpus.

`PgVectorStore` is the production implementation described in `AGENTS.md`. It
is optional because psycopg is not needed to run the pipeline locally.

Both refuse to compare vectors from different embedding models. That check is
the whole reason this module owns a `model_id` at all: a mismatch produces
plausible-looking distances that are pure noise, and nothing downstream can
tell.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .embeddings import cosine_similarity
from .errors import EmbeddingModelMismatch


@dataclass(frozen=True)
class VectorRecord:
    """One embedded item."""

    id: str
    vector: list[float]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SearchHit:
    """A record and its similarity to the query."""

    id: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)


class VectorStore(Protocol):
    """Stores vectors and answers nearest-neighbour queries."""

    @property
    def model_id(self) -> str: ...

    def upsert(self, records: list[VectorRecord]) -> None: ...

    def search(self, vector: list[float], *, limit: int = 5) -> list[SearchHit]: ...


class InMemoryVectorStore:
    """Exhaustive cosine search over a dict.

    Every query scores every record, so cost is linear in corpus size. That is
    the right trade for the ~10 candidate issues a single roadmap ranks, and
    the wrong one for anything larger; `PgVectorStore` is the answer there.
    """

    def __init__(self, model_id: str) -> None:
        self._model_id = model_id
        self._records: dict[str, VectorRecord] = {}

    @property
    def model_id(self) -> str:
        return self._model_id

    def __len__(self) -> int:
        return len(self._records)

    def upsert(self, records: list[VectorRecord]) -> None:
        for record in records:
            self._records[record.id] = record

    def search(self, vector: list[float], *, limit: int = 5) -> list[SearchHit]:
        hits = [
            SearchHit(
                id=record.id,
                score=cosine_similarity(vector, record.vector),
                metadata=record.metadata,
            )
            for record in self._records.values()
        ]
        hits.sort(key=lambda hit: hit.score, reverse=True)
        return hits[:limit]


class PgVectorStore:  # pragma: no cover - requires a live database
    """Postgres + pgvector, the production store from `AGENTS.md`.

    Not covered by the suite: exercising it needs a live database, which would
    put the network back into CI. It is integration-tested separately.
    """

    def __init__(self, connection, table: str, model_id: str) -> None:
        self._connection = connection
        self._table = table
        self._model_id = model_id

    @property
    def model_id(self) -> str:
        return self._model_id

    def upsert(self, records: list[VectorRecord]) -> None:
        with self._connection.cursor() as cursor:
            cursor.executemany(
                f"INSERT INTO {self._table} (id, embedding, metadata, embedding_model) "
                f"VALUES (%s, %s, %s, %s) "
                f"ON CONFLICT (id) DO UPDATE SET embedding = EXCLUDED.embedding, "
                f"metadata = EXCLUDED.metadata, embedding_model = EXCLUDED.embedding_model",
                [(r.id, r.vector, r.metadata, self._model_id) for r in records],
            )

    def search(self, vector: list[float], *, limit: int = 5) -> list[SearchHit]:
        with self._connection.cursor() as cursor:
            # The model filter is part of the query, not a check afterwards, so
            # rows written by a different embedding model can never be ranked.
            cursor.execute(
                f"SELECT id, 1 - (embedding <=> %s) AS score, metadata FROM {self._table} "
                f"WHERE embedding_model = %s ORDER BY embedding <=> %s LIMIT %s",
                (vector, self._model_id, vector, limit),
            )
            return [SearchHit(id=r[0], score=float(r[1]), metadata=r[2] or {}) for r in cursor]


def require_matching_model(store: VectorStore, provider_model_id: str) -> None:
    """Abort unless the store and the embedding provider agree on the model.

    Called before every write and every query. Vectors from two models occupy
    unrelated spaces, so a mismatch yields confident, meaningless scores.
    """
    if store.model_id != provider_model_id:
        raise EmbeddingModelMismatch(store=store.model_id, provider=provider_model_id)
