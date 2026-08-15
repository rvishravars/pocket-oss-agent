"""Coverage for the LangGraph orchestration.

What matters here is not that the agents work, which their own tests cover, but
that the graph wires them in the right order: the parallel branches, the join
before matching, and the interview pause surviving across two invocations.
"""

import pytest
from langgraph.types import Command

from pocket_oss_agent.errors import PipelineError, ResumeUnreadable
from pocket_oss_agent.graph import (
    CHECKPOINT_TYPES,
    PipelineState,
    build_graph,
    default_checkpointer,
    interview_prompt,
)
from pocket_oss_agent.state import SessionState

from .conftest import ANSWERS, REPO, RESUME, github_routes


def start(repo: str = REPO, **overrides) -> PipelineState:
    defaults = {
        "user_id": "u1",
        "repo_url": f"https://github.com/{repo}",
        "resume_text": RESUME,
    }
    return PipelineState(**{**defaults, **overrides})


def config(thread: str) -> dict:
    return {"configurable": {"thread_id": thread}}


class TestInterviewPause:
    async def test_the_graph_pauses_for_the_interview(self, deps) -> None:
        app = build_graph(deps)
        with github_routes():
            result = await app.ainvoke(start(), config("t1"))

        assert "__interrupt__" in result
        payload = result["__interrupt__"][0].value
        assert len(payload["questions"]) == 5
        assert payload["opening"]

    async def test_repo_work_completes_while_the_interview_waits(self, deps) -> None:
        """The whole reason the branches are parallel: the repo half of the
        pipeline should not idle while a human answers questions.
        """
        app = build_graph(deps)
        with github_routes():
            await app.ainvoke(start(), config("t2"))
            snapshot = await app.aget_state(config("t2"))

        assert snapshot.next == ("interview",)
        assert snapshot.values["repo_facts"] is not None
        assert snapshot.values["vibe_summary"] is not None
        assert snapshot.values["setup_steps"] is not None

    async def test_matching_waits_for_the_join(self, deps) -> None:
        """match_issues needs the interview and the repo. Separate edges would
        be OR-triggers and fire it off investigate_repo alone.
        """
        app = build_graph(deps)
        with github_routes():
            await app.ainvoke(start(), config("t3"))
            snapshot = await app.aget_state(config("t3"))

        # Unwritten keys are absent from the checkpoint rather than present as
        # None, so `.get` is the honest assertion: the node has not run at all.
        assert snapshot.values.get("top_match") is None
        assert snapshot.values.get("roadmap") is None

    async def test_resuming_runs_to_completion(self, deps) -> None:
        app = build_graph(deps)
        with github_routes():
            await app.ainvoke(start(), config("t4"))
            result = await app.ainvoke(Command(resume=ANSWERS), config("t4"))

        assert result["interview_context"].goal == "portfolio"
        assert result["roadmap"].startswith("# OSS Contribution Roadmap:")
        assert len(result["roadmap"].splitlines()) <= 60

    async def test_two_sessions_do_not_share_state(self, deps) -> None:
        app = build_graph(deps)
        with github_routes():
            await app.ainvoke(start(), config("a"))
            await app.ainvoke(start(), config("b"))
            await app.ainvoke(Command(resume=ANSWERS), config("a"))

            done = await app.aget_state(config("a"))
            still_waiting = await app.aget_state(config("b"))

        assert done.values["roadmap"]
        assert still_waiting.next == ("interview",)


class TestInputs:
    async def test_a_resume_path_is_accepted(self, deps, tmp_path) -> None:
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas

        target = tmp_path / "resume.pdf"
        pdf = canvas.Canvas(str(target), pagesize=letter)
        y = 740
        for line in RESUME.split(". "):
            pdf.drawString(60, y, line)
            y -= 16
        pdf.save()

        app = build_graph(deps)
        with github_routes():
            await app.ainvoke(start(resume_text=None, resume_path=str(target)), config("pdf"))
            snapshot = await app.aget_state(config("pdf"))

        assert snapshot.values["developer_context"].name == "Ada Okafor"

    async def test_no_resume_at_all_aborts(self, deps) -> None:
        app = build_graph(deps)
        with github_routes(), pytest.raises(PipelineError, match="no resume supplied"):
            await app.ainvoke(start(resume_text=None), config("none"))

    async def test_an_unreadable_resume_surfaces_as_a_pipeline_error(self, deps) -> None:
        app = build_graph(deps)
        with github_routes(), pytest.raises(ResumeUnreadable):
            await app.ainvoke(start(resume_text="too short"), config("short"))


class TestNoMatch:
    async def test_a_repo_with_no_candidates_still_produces_a_roadmap(self, deps) -> None:
        """top_match is a contractual null, so the roadmap renders the
        browse-manually fallback rather than the graph failing.
        """
        app = build_graph(deps)
        with github_routes(issues=[]):
            await app.ainvoke(start(), config("empty"))
            result = await app.ainvoke(Command(resume=ANSWERS), config("empty"))

        assert result["top_match"] is None
        assert "Your First Contribution" in result["roadmap"]


class TestCheckpointing:
    def test_every_session_state_model_can_round_trip(self) -> None:
        """LangGraph warns on unregistered types today and will block them.
        Anything on SessionState must therefore be listed.
        """
        registered = {name for _module, name in CHECKPOINT_TYPES}
        for field in SessionState.model_fields.values():
            annotation = str(field.annotation)
            for candidate in registered:
                if candidate in annotation:
                    break
            else:
                assert "str" in annotation or "None" in annotation, (
                    f"unregistered model in session state: {annotation}"
                )

    def test_the_default_checkpointer_registers_this_project(self) -> None:
        saver = default_checkpointer()
        assert saver.serde is not None


class TestInterviewPrompt:
    def test_carries_everything_a_client_needs_to_render(self, deps) -> None:
        from pocket_oss_agent.state import DeveloperContext

        payload = interview_prompt(
            PipelineState(user_id="u", developer_context=DeveloperContext(seniority="junior"))
        )

        assert "no wrong answers" in payload["opening"]
        keys = [q["key"] for q in payload["questions"]]
        assert keys == [
            "goal",
            "time_commitment",
            "contribution_types",
            "risk_tolerance",
            "collaboration_style",
        ]
        multi = [q["key"] for q in payload["questions"] if q["multi_select"]]
        assert multi == ["contribution_types"]
        assert all(q["options"] for q in payload["questions"])
