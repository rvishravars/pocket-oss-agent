"""LangGraph orchestration for the eight-agent pipeline.

The pipeline is a static DAG, so most of it would compose fine with plain
async. What earns LangGraph is the interview: it needs a human mid-run, and
`interrupt` plus a checkpointer is what lets the graph pause across an HTTP
request and resume with the answers.

    START ─┬─> parse_resume ──> interview ──────────┐
           │                                        ├─> match_issues ──┐
           └─> investigate_repo ────────────────────┘                  ├─> roadmap ─> END
                     ├─> repo_analyst (cached) ──────────────────────────┤
                     ├─> validate_setup ─────────────────────────────────┤
                     └─> check_vibe ──────────────────────────────────────┘

`repo_analyst` is the one node that may run once and never again for a given
repository: it checks `RepoIntelligenceStore` before doing any work, so a
repeat request for a repository already analyzed costs nothing extra here.
Its output is a nullable enrichment, not a required input - a cache miss that
fails (no key configured, a Claude error) still lets the roadmap render, the
same way `skill-matcher` finding no confident match does.

Dependencies arrive as an injected `Dependencies` bundle rather than being
constructed in nodes, so the graph is testable with fakes and CI never needs a
key, a model download or a database.
"""

from __future__ import annotations

from dataclasses import dataclass

from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from .agents.env_validator import validate_setup
from .agents.interviewer import QUESTION_BANK, conduct_interview, opening_line
from .agents.repo_analyst import RepoAnalyzer, analyze_repo
from .agents.repo_investigator import investigate
from .agents.resume_parser import parse_resume, parse_resume_text
from .agents.skill_matcher import match_issues
from .agents.strategy_generator import generate_roadmap
from .agents.vibe_checker import check_vibe
from .embeddings import EmbeddingProvider
from .errors import PipelineError
from .github_client import GitHubClient
from .llm import ProfileExtractor
from .repo_intelligence_store import RepoIntelligenceStore
from .state import SessionState
from .vector_store import VectorStore


class PipelineState(SessionState):
    """Session state plus the run's inputs.

    Extends `SessionState` rather than duplicating it, so the graph and the API
    speak exactly the schema in `AGENTS.md`.
    """

    repo_url: str = ""
    resume_path: str | None = None
    resume_text: str | None = None


#: The session-state models a checkpoint round-trips. LangGraph deserializes
#: unregistered types with a warning today and will block them outright in a
#: future release, so name them explicitly rather than relying on the
#: permissive default. Anything new on `SessionState` belongs here too.
CHECKPOINT_TYPES: tuple[tuple[str, str], ...] = (
    ("pocket_oss_agent.state", "DeveloperContext"),
    ("pocket_oss_agent.state", "InterviewContext"),
    ("pocket_oss_agent.state", "RepoFacts"),
    ("pocket_oss_agent.state", "GoodFirstIssue"),
    ("pocket_oss_agent.state", "RepoIntelligence"),
    ("pocket_oss_agent.state", "IssueIntelligence"),
    ("pocket_oss_agent.state", "SetupSteps"),
    ("pocket_oss_agent.state", "SetupStep"),
    ("pocket_oss_agent.state", "VibeSummary"),
    ("pocket_oss_agent.state", "TopMatch"),
    ("pocket_oss_agent.graph", "PipelineState"),
)


def default_checkpointer() -> MemorySaver:
    """An in-memory checkpointer that round-trips this project's state models.

    In-memory keeps CI offline and needs no database. A Postgres saver drops in
    behind the same seam for production; it takes the same serializer.
    """
    return MemorySaver(serde=JsonPlusSerializer(allowed_msgpack_modules=CHECKPOINT_TYPES))


@dataclass
class Dependencies:
    """Everything the nodes need from outside.

    Held as one bundle so a caller wires fakes once. The GitHub client is a
    live instance rather than a factory: three nodes call it, and sharing one
    connection pool across them is the point.
    """

    extractor: ProfileExtractor
    embeddings: EmbeddingProvider
    github: GitHubClient
    store: VectorStore | None = None
    #: Both optional together: `repo-analyst` is a nullable enrichment, so a
    #: deployment that has not configured Sonnet access for it (or wants to
    #: avoid the cost) simply runs without repo intelligence rather than
    #: failing to build a graph at all.
    repo_analyzer: RepoAnalyzer | None = None
    repo_intelligence_store: RepoIntelligenceStore | None = None


def interview_prompt(state: PipelineState) -> dict:
    """The payload surfaced to the client while the graph is paused."""
    return {
        "opening": opening_line(state.developer_context),
        "questions": [
            {
                "key": category.key,
                "prompt": category.prompt,
                "required": category.required,
                "multi_select": category.multi_select,
                "options": [
                    {"value": option.value, "label": option.label} for option in category.options
                ],
            }
            for category in QUESTION_BANK
        ],
    }


def build_graph(deps: Dependencies, checkpointer=None):
    """Compile the pipeline.

    A checkpointer is required for the interview to survive the pause. Defaults
    to `MemorySaver`, which keeps CI offline; swap in a Postgres saver for
    production without touching this function's callers.
    """

    async def parse_resume_node(state: PipelineState) -> dict:
        if state.resume_text:
            context = parse_resume_text(
                state.resume_text,
                deps.extractor,
                embeddings=deps.embeddings if deps.store else None,
                store=deps.store,
                user_id=state.user_id if deps.store else None,
            )
        elif state.resume_path:
            context = parse_resume(
                state.resume_path,
                deps.extractor,
                embeddings=deps.embeddings if deps.store else None,
                store=deps.store,
                user_id=state.user_id if deps.store else None,
            )
        else:
            raise PipelineError("no resume supplied: set resume_path or resume_text")
        return {"developer_context": context}

    async def investigate_node(state: PipelineState) -> dict:
        return {"repo_facts": await investigate(state.repo_url, deps.github)}

    async def repo_analyst_node(state: PipelineState) -> dict:
        if deps.repo_analyzer is None or deps.repo_intelligence_store is None:
            return {"repo_intelligence": None}
        try:
            intelligence = await analyze_repo(
                state.repo_facts, deps.github, deps.repo_analyzer, deps.repo_intelligence_store
            )
        except PipelineError:
            # repo_intelligence is a nullable enrichment, not a required
            # input - skill-matcher and the roadmap already render without
            # it, the same way a skill-matcher miss renders a fallback
            # rather than aborting the whole run.
            return {"repo_intelligence": None}
        return {"repo_intelligence": intelligence}

    async def interview_node(state: PipelineState) -> dict:
        # Pauses here on the first pass. The value handed to Command(resume=...)
        # comes back as `answers` when the graph is resumed.
        answers = interrupt(interview_prompt(state))
        return {"interview_context": conduct_interview(state.developer_context, answers)}

    async def validate_setup_node(state: PipelineState) -> dict:
        return {"setup_steps": await validate_setup(state.repo_facts, deps.github)}

    async def check_vibe_node(state: PipelineState) -> dict:
        return {"vibe_summary": await check_vibe(state.repo_facts, deps.github)}

    async def match_node(state: PipelineState) -> dict:
        top_match, _filters, _ranked = match_issues(
            state.developer_context,
            state.interview_context,
            state.repo_facts,
            embeddings=deps.embeddings,
            store=deps.store,
            repo_intelligence=state.repo_intelligence,
        )
        # top_match is a contractual null when nothing clears the floor, so it
        # is written even when None; the roadmap renders the fallback.
        return {"top_match": top_match}

    async def roadmap_node(state: PipelineState) -> dict:
        return {
            "roadmap": generate_roadmap(
                developer_context=state.developer_context,
                interview_context=state.interview_context,
                repo_facts=state.repo_facts,
                setup_steps=state.setup_steps,
                vibe_summary=state.vibe_summary,
                top_match=state.top_match,
                repo_intelligence=state.repo_intelligence,
            )
        }

    graph = StateGraph(PipelineState)
    graph.add_node("parse_resume", parse_resume_node)
    graph.add_node("investigate_repo", investigate_node)
    graph.add_node("repo_analyst", repo_analyst_node)
    graph.add_node("interview", interview_node)
    graph.add_node("validate_setup", validate_setup_node)
    graph.add_node("check_vibe", check_vibe_node)
    graph.add_node("match_issues", match_node)
    graph.add_node("roadmap", roadmap_node)

    # Resume parsing and repo investigation share no inputs, so they run at once.
    graph.add_edge(START, "parse_resume")
    graph.add_edge(START, "investigate_repo")

    # The interview personalizes its phrasing from the profile.
    graph.add_edge("parse_resume", "interview")

    # All three need only repo_facts, so they run in parallel once it lands.
    graph.add_edge("investigate_repo", "repo_analyst")
    graph.add_edge("investigate_repo", "validate_setup")
    graph.add_edge("investigate_repo", "check_vibe")

    # The list form is a real join: the node waits for every named predecessor.
    # Separate add_edge calls would be OR-triggers, which fires match_issues off
    # investigate_repo alone while the interview is still suspended, and it then
    # aborts on the missing interview_context.
    graph.add_edge(["interview", "investigate_repo", "repo_analyst"], "match_issues")
    graph.add_edge(["match_issues", "validate_setup", "check_vibe", "repo_analyst"], "roadmap")
    graph.add_edge("roadmap", END)

    return graph.compile(checkpointer=checkpointer or default_checkpointer())
