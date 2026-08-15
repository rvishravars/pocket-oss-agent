"""Coverage for embedding providers and the vector store."""

import sys
import types

import pytest

from pocket_oss_agent.embeddings import (
    DEFAULT_MODEL,
    DeterministicEmbeddings,
    SentenceTransformerEmbeddings,
    cosine_similarity,
)
from pocket_oss_agent.errors import EmbeddingModelMismatch
from pocket_oss_agent.vector_store import (
    InMemoryVectorStore,
    SearchHit,
    VectorRecord,
    require_matching_model,
)


class TestDeterministicEmbeddings:
    def test_same_text_yields_the_same_vector(self) -> None:
        embedder = DeterministicEmbeddings(dimensions=32)
        assert embedder.embed(["hello world"]) == embedder.embed(["hello world"])

    def test_vectors_are_unit_length(self) -> None:
        [vector] = DeterministicEmbeddings(dimensions=32).embed(["python go rust"])
        assert cosine_similarity(vector, vector) == pytest.approx(1.0)

    def test_dimensions_and_model_id_are_reported(self) -> None:
        embedder = DeterministicEmbeddings(dimensions=16)
        assert embedder.dimensions == 16
        assert "16" in embedder.model_id

    def test_model_id_is_distinct_from_a_real_model(self) -> None:
        """A store built with the fake must not be queryable with real vectors."""
        assert DEFAULT_MODEL not in DeterministicEmbeddings().model_id

    def test_empty_text_embeds_to_a_zero_vector(self) -> None:
        [vector] = DeterministicEmbeddings(dimensions=8).embed([""])
        assert vector == [0.0] * 8

    def test_embedding_nothing_returns_nothing(self) -> None:
        assert DeterministicEmbeddings(dimensions=8).embed([]) == []

    def test_rejects_a_nonsense_dimension(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            DeterministicEmbeddings(dimensions=0)

    def test_case_and_punctuation_do_not_change_the_vector(self) -> None:
        embedder = DeterministicEmbeddings(dimensions=32)
        assert embedder.embed(["Python, Go"]) == embedder.embed(["python go"])


class TestCosineSimilarity:
    def test_a_zero_vector_scores_zero_rather_than_dividing_by_zero(self) -> None:
        assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0
        assert cosine_similarity([1.0, 0.0], [0.0, 0.0]) == 0.0

    def test_opposite_vectors_score_negative_one(self) -> None:
        assert cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)

    def test_mismatched_dimensions_are_an_error(self) -> None:
        with pytest.raises(ValueError, match="dimension mismatch"):
            cosine_similarity([1.0], [1.0, 0.0])


class TestSentenceTransformerEmbeddings:
    """Exercised against a stubbed module.

    Installing the real package pulls in torch, which is far too heavy for CI.
    What is tested is this wrapper's own logic, not the model.
    """

    @pytest.fixture
    def stub_module(self, monkeypatch):
        class StubModel:
            def __init__(self, name: str) -> None:
                self.name = name
                self.seen: list[list[str]] = []

            def get_embedding_dimension(self) -> int:
                return 384

            def encode(self, texts, normalize_embeddings=False):
                self.seen.append(list(texts))
                assert normalize_embeddings, "vectors must arrive normalized"
                return [[0.5, 0.5] for _ in texts]

        module = types.ModuleType("sentence_transformers")
        module.SentenceTransformer = StubModel
        monkeypatch.setitem(sys.modules, "sentence_transformers", module)
        return module

    def test_reports_the_model_name_and_dimensions(self, stub_module) -> None:
        embedder = SentenceTransformerEmbeddings()
        assert embedder.model_id == DEFAULT_MODEL
        assert embedder.dimensions == 384

    def test_falls_back_to_the_pre_v5_dimension_getter(self, monkeypatch) -> None:
        """sentence-transformers 5 renamed the method; both majors are supported."""
        import sys
        import types

        class LegacyModel:
            def __init__(self, name: str) -> None:
                self.name = name

            def get_sentence_embedding_dimension(self) -> int:
                return 768

            def encode(self, texts, normalize_embeddings=False):
                return [[1.0] for _ in texts]

        module = types.ModuleType("sentence_transformers")
        module.SentenceTransformer = LegacyModel
        monkeypatch.setitem(sys.modules, "sentence_transformers", module)

        assert SentenceTransformerEmbeddings().dimensions == 768

    def test_requests_normalized_vectors(self, stub_module) -> None:
        vectors = SentenceTransformerEmbeddings().embed(["a", "b"])
        assert vectors == [[0.5, 0.5], [0.5, 0.5]]

    def test_embedding_nothing_skips_the_model(self, stub_module) -> None:
        embedder = SentenceTransformerEmbeddings()
        assert embedder.embed([]) == []
        assert embedder._model.seen == []

    def test_a_missing_extra_says_how_to_install_it(self, monkeypatch) -> None:
        monkeypatch.setitem(sys.modules, "sentence_transformers", None)
        with pytest.raises(ImportError, match=r"embeddings"):
            SentenceTransformerEmbeddings()


class TestInMemoryVectorStore:
    def test_upsert_then_search_returns_the_nearest_first(self) -> None:
        store = InMemoryVectorStore(model_id="stub")
        store.upsert(
            [
                VectorRecord(id="near", vector=[1.0, 0.0]),
                VectorRecord(id="far", vector=[0.0, 1.0]),
            ]
        )
        hits = store.search([1.0, 0.0])

        assert [hit.id for hit in hits] == ["near", "far"]
        assert hits[0].score == pytest.approx(1.0)

    def test_upsert_replaces_by_id(self) -> None:
        store = InMemoryVectorStore(model_id="stub")
        store.upsert([VectorRecord(id="a", vector=[1.0, 0.0])])
        store.upsert([VectorRecord(id="a", vector=[0.0, 1.0])])

        assert len(store) == 1
        assert store.search([0.0, 1.0])[0].score == pytest.approx(1.0)

    def test_limit_is_respected(self) -> None:
        store = InMemoryVectorStore(model_id="stub")
        store.upsert([VectorRecord(id=str(n), vector=[1.0, float(n)]) for n in range(10)])
        assert len(store.search([1.0, 0.0], limit=3)) == 3

    def test_metadata_survives_the_round_trip(self) -> None:
        store = InMemoryVectorStore(model_id="stub")
        store.upsert([VectorRecord(id="a", vector=[1.0, 0.0], metadata={"title": "Fix crash"})])
        assert store.search([1.0, 0.0])[0].metadata == {"title": "Fix crash"}

    def test_searching_an_empty_store_returns_nothing(self) -> None:
        assert InMemoryVectorStore(model_id="stub").search([1.0, 0.0]) == []

    def test_a_hit_defaults_to_empty_metadata(self) -> None:
        assert SearchHit(id="a", score=1.0).metadata == {}


class TestModelGuard:
    def test_matching_models_pass(self) -> None:
        require_matching_model(InMemoryVectorStore(model_id="same"), "same")

    def test_a_mismatch_names_both_sides_and_says_why(self) -> None:
        with pytest.raises(EmbeddingModelMismatch) as excinfo:
            require_matching_model(InMemoryVectorStore(model_id="stored"), "provider")

        message = str(excinfo.value)
        assert "stored" in message and "provider" in message
        assert "meaningless" in message
