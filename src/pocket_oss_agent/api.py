"""FastAPI surface over the pipeline graph.

The interview is what shapes this API. The graph pauses mid-run waiting for a
human, so a session is a first-class resource: start it, poll it, answer the
interview, collect the roadmap.

    POST /sessions                  start a run, returns a session id
    GET  /sessions/{id}             status, plus the questions while paused
    POST /sessions/{id}/interview   answers; resumes the graph
    GET  /sessions/{id}/roadmap     the finished Markdown

`create_app` takes an optional `Dependencies` bundle, so a test builds the whole
app against fakes with no key, no model download and no database.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Request, status
from langgraph.types import Command
from pydantic import BaseModel, Field

from .embeddings import DeterministicEmbeddings
from .errors import PipelineError
from .github_client import GitHubClient
from .graph import Dependencies, PipelineState, build_graph, default_checkpointer
from .llm import ClaudeProfileExtractor

#: Starlette renamed HTTP_422_UNPROCESSABLE_ENTITY to ..._CONTENT and
#: deprecated the old spelling. Resolve once so both versions work.
UNPROCESSABLE = (
    getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", None) or status.HTTP_422_UNPROCESSABLE_ENTITY
)


class SessionStatus(StrEnum):
    AWAITING_INTERVIEW = "awaiting_interview"
    COMPLETE = "complete"


class StartSession(BaseModel):
    repo_url: str = Field(description="owner/name or a GitHub URL")
    resume_text: str | None = Field(default=None, description="Resume text")
    resume_path: str | None = Field(default=None, description="Path to a PDF resume")
    user_id: str = Field(default="anonymous")


class SessionCreated(BaseModel):
    session_id: str
    status: SessionStatus
    interview: dict[str, Any] | None = None


class SessionView(BaseModel):
    session_id: str
    status: SessionStatus
    interview: dict[str, Any] | None = None
    repo: str | None = None
    candidate_issues: int | None = None


class InterviewAnswers(BaseModel):
    """Answers keyed by question, matching `QUESTION_BANK`."""

    answers: dict[str, Any]


class Roadmap(BaseModel):
    session_id: str
    roadmap: str
    matched_issue_id: int | None = None


@dataclass
class AppState:
    """Process-wide objects, built once at startup rather than per request."""

    graph: Any
    github: GitHubClient


def get_state(request: Request) -> AppState:
    """Resolve the process-wide state for a request.

    Module level on purpose. With `from __future__ import annotations` every
    annotation is a string that FastAPI resolves in module scope, so an alias
    defined inside `create_app` is invisible and the parameter silently becomes
    a query field.
    """
    return request.app.state.app_state


#: Annotated rather than a `Depends()` default: FastAPI reads both, but a call
#: in a default argument is a lint error and an easy footgun elsewhere.
CurrentState = Annotated[AppState, Depends(get_state)]


def build_dependencies(github: GitHubClient) -> Dependencies:
    """Production wiring.

    `DeterministicEmbeddings` is the default because the real embedder pulls in
    torch, which is an opt-in extra. Swap it here, not in the agents.
    """
    return Dependencies(
        extractor=ClaudeProfileExtractor(),
        embeddings=DeterministicEmbeddings(),
        github=github,
    )


def create_app(dependencies: Dependencies | None = None, checkpointer=None) -> FastAPI:
    """Build the app.

    Passing `dependencies` skips the production wiring entirely, which is how
    tests avoid needing any credential.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if dependencies is not None:
            app.state.app_state = AppState(
                graph=build_graph(dependencies, checkpointer or default_checkpointer()),
                github=dependencies.github,
            )
            yield
            return

        # One client for the process: three nodes call GitHub, and sharing a
        # connection pool across them is the point.
        async with GitHubClient() as github:
            deps = build_dependencies(github)
            app.state.app_state = AppState(
                graph=build_graph(deps, checkpointer or default_checkpointer()),
                github=github,
            )
            yield

    app = FastAPI(
        title="Pocket OSS Agent",
        description="Turns a resume and a repository into a one-page contribution roadmap.",
        lifespan=lifespan,
    )

    @app.post("/sessions", response_model=SessionCreated, status_code=status.HTTP_201_CREATED)
    async def start_session(body: StartSession, state: CurrentState):
        if not body.resume_text and not body.resume_path:
            raise HTTPException(
                UNPROCESSABLE,
                "supply resume_text or resume_path",
            )

        session_id = uuid.uuid4().hex
        config = _config(session_id)
        initial = PipelineState(
            user_id=body.user_id,
            repo_url=body.repo_url,
            resume_text=body.resume_text,
            resume_path=body.resume_path,
        )
        result = await _run(state.graph, initial, config)
        return SessionCreated(
            session_id=session_id,
            status=_status(result),
            interview=_interview(result),
        )

    @app.get("/sessions/{session_id}", response_model=SessionView)
    async def get_session(session_id: str, state: CurrentState):
        snapshot = await state.graph.aget_state(_config(session_id))
        if not snapshot.created_at:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"no session {session_id!r}")

        values = snapshot.values
        facts = values.get("repo_facts")
        paused = bool(snapshot.next)
        return SessionView(
            session_id=session_id,
            status=SessionStatus.AWAITING_INTERVIEW if paused else SessionStatus.COMPLETE,
            interview=_interrupt_payload(snapshot),
            repo=facts.slug if facts else None,
            candidate_issues=len(facts.good_first_issues) if facts else None,
        )

    @app.post("/sessions/{session_id}/interview", response_model=SessionCreated)
    async def answer_interview(session_id: str, body: InterviewAnswers, state: CurrentState):
        config = _config(session_id)
        snapshot = await state.graph.aget_state(config)
        if not snapshot.created_at:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"no session {session_id!r}")
        if not snapshot.next:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "this session is not waiting for an interview"
            )

        result = await _run(state.graph, Command(resume=body.answers), config)
        return SessionCreated(
            session_id=session_id,
            status=_status(result),
            interview=_interview(result),
        )

    @app.get("/sessions/{session_id}/roadmap", response_model=Roadmap)
    async def get_roadmap(session_id: str, state: CurrentState):
        snapshot = await state.graph.aget_state(_config(session_id))
        if not snapshot.created_at:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"no session {session_id!r}")

        roadmap = snapshot.values.get("roadmap")
        if not roadmap:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "the roadmap is not ready; the session is still awaiting the interview",
            )
        match = snapshot.values.get("top_match")
        return Roadmap(
            session_id=session_id,
            roadmap=roadmap,
            matched_issue_id=match.issue_id if match else None,
        )

    return app


async def _run(graph, payload, config) -> dict:
    """Advance the graph, turning a pipeline failure into a 422.

    A `PipelineError` means the inputs cannot produce a roadmap: an unreadable
    resume, a repository that does not exist. That is the caller's problem to
    fix, so it is reported rather than surfaced as a 500.
    """
    try:
        return await graph.ainvoke(payload, config)
    except PipelineError as exc:
        raise HTTPException(UNPROCESSABLE, str(exc)) from exc


def _config(session_id: str) -> dict:
    return {"configurable": {"thread_id": session_id}}


def _status(result: dict) -> SessionStatus:
    return SessionStatus.AWAITING_INTERVIEW if "__interrupt__" in result else SessionStatus.COMPLETE


def _interview(result: dict) -> dict | None:
    interrupts = result.get("__interrupt__")
    return interrupts[0].value if interrupts else None


def _interrupt_payload(snapshot) -> dict | None:
    """The interview payload from a paused snapshot, or None if it is running.

    A completed session has tasks with no interrupts, so flatten rather than
    branching per task.
    """
    pending = [i for task in snapshot.tasks for i in getattr(task, "interrupts", ())]
    return pending[0].value if pending else None
