"""Coverage for the HTTP surface.

Driven through a real ASGI transport rather than by calling the handlers, so
routing, validation, status codes and the lifespan are all exercised.
"""

import httpx
import pytest
from asgi_lifespan import LifespanManager

from pocket_oss_agent.api import UNPROCESSABLE, create_app

from .conftest import ANSWERS, REPO, RESUME, github_routes


@pytest.fixture
async def client(deps):
    app = create_app(dependencies=deps)
    async with (
        LifespanManager(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test", timeout=30
        ) as http,
    ):
        yield http


def start_body(**overrides) -> dict:
    return {"repo_url": f"https://github.com/{REPO}", "resume_text": RESUME, **overrides}


async def start_session(client) -> str:
    response = await client.post("/sessions", json=start_body())
    assert response.status_code == 201
    return response.json()["session_id"]


class TestStartSession:
    async def test_returns_the_interview_while_paused(self, client) -> None:
        with github_routes():
            response = await client.post("/sessions", json=start_body())

        body = response.json()
        assert response.status_code == 201
        assert body["status"] == "awaiting_interview"
        assert len(body["interview"]["questions"]) == 5
        assert body["session_id"]

    async def test_requires_a_resume(self, client) -> None:
        response = await client.post("/sessions", json={"repo_url": REPO})
        assert response.status_code == UNPROCESSABLE
        assert "resume" in response.json()["detail"]

    async def test_a_bad_repo_url_is_the_callers_problem(self, client) -> None:
        """A PipelineError means the inputs cannot produce a roadmap, so it is
        reported rather than surfaced as a 500.
        """
        with github_routes():
            response = await client.post("/sessions", json=start_body(repo_url="not a repo"))

        assert response.status_code == UNPROCESSABLE
        assert "not a repo" in response.json()["detail"]

    async def test_sessions_get_distinct_ids(self, client) -> None:
        with github_routes():
            first = await start_session(client)
            second = await start_session(client)
        assert first != second


class TestGetSession:
    async def test_reports_progress_made_while_paused(self, client) -> None:
        with github_routes():
            session_id = await start_session(client)
            response = await client.get(f"/sessions/{session_id}")

        body = response.json()
        assert body["status"] == "awaiting_interview"
        assert body["repo"] == REPO
        assert body["candidate_issues"] == 1
        assert len(body["interview"]["questions"]) == 5

    async def test_unknown_session_is_a_404(self, client) -> None:
        assert (await client.get("/sessions/nope")).status_code == 404


class TestInterview:
    async def test_answers_resume_the_run(self, client) -> None:
        with github_routes():
            session_id = await start_session(client)
            response = await client.post(
                f"/sessions/{session_id}/interview", json={"answers": ANSWERS}
            )

        assert response.status_code == 200
        assert response.json()["status"] == "complete"

    async def test_answering_twice_is_a_conflict(self, client) -> None:
        with github_routes():
            session_id = await start_session(client)
            await client.post(f"/sessions/{session_id}/interview", json={"answers": ANSWERS})
            again = await client.post(
                f"/sessions/{session_id}/interview", json={"answers": ANSWERS}
            )

        assert again.status_code == 409
        assert "not waiting" in again.json()["detail"]

    async def test_incomplete_answers_are_reported(self, client) -> None:
        """The interviewer treats a skipped mandatory category as a validation
        error, and that has to reach the caller rather than 500.
        """
        with github_routes():
            session_id = await start_session(client)
            response = await client.post(
                f"/sessions/{session_id}/interview", json={"answers": {"goal": "portfolio"}}
            )

        assert response.status_code == UNPROCESSABLE
        assert "risk_tolerance" in response.json()["detail"]

    async def test_unknown_session_is_a_404(self, client) -> None:
        response = await client.post("/sessions/nope/interview", json={"answers": ANSWERS})
        assert response.status_code == 404


class TestRoadmap:
    async def test_returns_the_markdown_and_the_match(self, client) -> None:
        with github_routes():
            session_id = await start_session(client)
            await client.post(f"/sessions/{session_id}/interview", json={"answers": ANSWERS})
            response = await client.get(f"/sessions/{session_id}/roadmap")

        body = response.json()
        assert response.status_code == 200
        assert body["roadmap"].startswith("# OSS Contribution Roadmap:")
        assert len(body["roadmap"].splitlines()) <= 60
        assert body["matched_issue_id"] == 7

    async def test_asking_before_the_interview_is_a_conflict(self, client) -> None:
        with github_routes():
            session_id = await start_session(client)
            response = await client.get(f"/sessions/{session_id}/roadmap")

        assert response.status_code == 409
        assert "not ready" in response.json()["detail"]

    async def test_a_repo_with_no_candidates_still_returns_a_roadmap(self, client) -> None:
        with github_routes(issues=[]):
            session_id = await start_session(client)
            await client.post(f"/sessions/{session_id}/interview", json={"answers": ANSWERS})
            response = await client.get(f"/sessions/{session_id}/roadmap")

        assert response.status_code == 200
        assert response.json()["matched_issue_id"] is None

    async def test_unknown_session_is_a_404(self, client) -> None:
        assert (await client.get("/sessions/nope/roadmap")).status_code == 404


class TestWiring:
    async def test_the_app_documents_itself(self, client) -> None:
        schema = (await client.get("/openapi.json")).json()
        assert set(schema["paths"]) == {
            "/sessions",
            "/sessions/{session_id}",
            "/sessions/{session_id}/interview",
            "/sessions/{session_id}/roadmap",
        }

    def test_production_wiring_needs_no_credential_to_construct(self) -> None:
        """create_app must not build a Claude client at import or call time;
        that happens in the lifespan, so the module stays importable without a
        key and CI can exercise the app.
        """
        assert create_app() is not None

    async def test_a_completed_session_reports_no_interview(self, client) -> None:
        with github_routes():
            session_id = await start_session(client)
            await client.post(f"/sessions/{session_id}/interview", json={"answers": ANSWERS})
            response = await client.get(f"/sessions/{session_id}")

        body = response.json()
        assert body["status"] == "complete"
        assert body["interview"] is None

    async def test_the_production_lifespan_wires_itself(self, monkeypatch) -> None:
        """Exercises the no-dependencies path: the app builds its own GitHub
        client, Claude extractor, embedder and graph at startup. The anthropic
        and sentence_transformers modules are stubbed so this needs no
        credential, no model download, and makes no call.
        """
        import sys
        import types

        anthropic_module = types.ModuleType("anthropic")
        anthropic_module.Anthropic = lambda: object()
        monkeypatch.setitem(sys.modules, "anthropic", anthropic_module)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        class StubModel:
            def __init__(self, name: str) -> None:
                pass

            def get_embedding_dimension(self) -> int:
                return 384

            def encode(self, texts, normalize_embeddings=False):
                return [[0.5, 0.5] for _ in texts]

        st_module = types.ModuleType("sentence_transformers")
        st_module.SentenceTransformer = StubModel
        monkeypatch.setitem(sys.modules, "sentence_transformers", st_module)

        app = create_app()
        async with LifespanManager(app):
            state = app.state.app_state
            assert state.graph is not None
            assert state.github is not None
