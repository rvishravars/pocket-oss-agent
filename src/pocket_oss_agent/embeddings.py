"""Embedding providers.

`AGENTS.md` requires every vector in the system to come from one model: mixing
models silently produces meaningless cosine distances, and nothing downstream
can detect it. Each provider therefore reports a `model_id`, and
`vector_store` refuses to mix them.

`SentenceTransformerEmbeddings` is the production implementation. It is an
optional dependency because it pulls in torch, which is far too heavy to
install on four Python versions in CI; the suite runs against
`DeterministicEmbeddings` instead, which needs nothing.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol

DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_DIMENSIONS = 384


class EmbeddingProvider(Protocol):
    """Turns text into vectors."""

    @property
    def model_id(self) -> str: ...

    @property
    def dimensions(self) -> int: ...

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class SentenceTransformerEmbeddings:
    """Local embeddings, no API key and no network at query time.

    Install with the `embeddings` extra. The model is downloaded once on first
    use and cached by sentence-transformers.
    """

    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise ImportError(
                "SentenceTransformerEmbeddings needs the 'embeddings' extra: "
                'pip install -e ".[embeddings]"'
            ) from exc
        self._model_name = model_name
        self._model = SentenceTransformer(model_name)

    @property
    def model_id(self) -> str:
        return self._model_name

    @property
    def dimensions(self) -> int:
        # Renamed in sentence-transformers 5; the old name still works but
        # warns. Prefer the new one and fall back so both majors are supported.
        getter = getattr(self._model, "get_embedding_dimension", None) or (
            self._model.get_sentence_embedding_dimension
        )
        return int(getter())

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = self._model.encode(texts, normalize_embeddings=True)
        return [[float(value) for value in vector] for vector in vectors]


class DeterministicEmbeddings:
    """A hashing embedder: same text always yields the same vector.

    Not semantic. It exists so the pipeline, the store, and the ranking maths
    can be tested end to end without downloading a model, and so local
    development works before anyone installs the extra. Its `model_id` is
    deliberately distinct, so a store built with it cannot silently be queried
    with real vectors.
    """

    def __init__(self, dimensions: int = DEFAULT_DIMENSIONS) -> None:
        if dimensions <= 0:
            raise ValueError("dimensions must be positive")
        self._dimensions = dimensions

    @property
    def model_id(self) -> str:
        return f"deterministic-hashing-{self._dimensions}"

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self._dimensions
        for token in _tokenize(text):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "big") % self._dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign
        return _normalize(vector)


def cosine_similarity(left: list[float], right: list[float]) -> float:
    """Cosine similarity, safe on zero vectors.

    A zero vector has no direction, so its similarity to anything is 0.0 rather
    than a division error. Empty text embeds to zero, which is reachable.
    """
    if len(left) != len(right):
        raise ValueError(f"dimension mismatch: {len(left)} vs {len(right)}")
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9+#.]+", text.lower())


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0.0:
        return vector
    return [value / norm for value in vector]
