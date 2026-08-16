#!/usr/bin/env python3
"""Run the implemented agents against a real repository and print the roadmap.

Every significant bug in this codebase passed its mocked tests first. Mocks
confirm the code does what you assumed; only live data challenges the
assumption. This is the harness for that check.

    GITHUB_TOKEN=$(gh auth token) python scripts/run_pipeline.py pallets/flask

All seven agents are real. `resume-parser` runs only when `--resume` is given,
since it needs an API key; without it the stand-in profile below is used so the
rest of the pipeline stays runnable.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from pocket_oss_agent.agents.env_validator import validate_setup
from pocket_oss_agent.agents.interviewer import conduct_interview
from pocket_oss_agent.agents.repo_investigator import investigate
from pocket_oss_agent.agents.resume_parser import parse_resume
from pocket_oss_agent.agents.skill_matcher import MINIMUM_SCORE, is_confident, match_issues
from pocket_oss_agent.agents.strategy_generator import generate_roadmap, verify_roadmap
from pocket_oss_agent.agents.vibe_checker import check_vibe
from pocket_oss_agent.embeddings import DeterministicEmbeddings
from pocket_oss_agent.errors import PipelineError
from pocket_oss_agent.github_client import GitHubClient
from pocket_oss_agent.llm import ClaudeProfileExtractor
from pocket_oss_agent.state import DeveloperContext, SessionState

# --- stand-in profile, used when no resume is supplied -----------------------

STAND_IN_DEVELOPER = DeveloperContext(
    name="Ada Okafor",
    languages=["Python", "Go"],
    frameworks=["FastAPI"],
    tools=["Docker", "AWS"],
    years_experience=5,
    seniority="mid",
    domain="backend",
)

STAND_IN_ANSWERS = {
    "goal": "portfolio",
    "time_commitment": "light",
    "contribution_types": ["bugfix", "docs"],
    "risk_tolerance": "low",
    "collaboration_style": "guided",
}


# --- pipeline ----------------------------------------------------------------


def build_embeddings(prefer_real: bool):
    """Return the embedder to rank with, and whether it is semantic.

    `DeterministicEmbeddings` hashes tokens; it is not semantic, so similarity
    between a skills list and an issue title lands far below `MINIMUM_SCORE`
    and every repo falls back to browse-manually. That is a property of the
    stand-in, not of the repo, so the harness says which one ran.
    """
    if prefer_real:
        try:
            from pocket_oss_agent.embeddings import SentenceTransformerEmbeddings

            return SentenceTransformerEmbeddings(), True
        except ImportError as exc:
            print(f"note: {exc}", file=sys.stderr)
    return DeterministicEmbeddings(), False


async def run(
    repo: str,
    *,
    answers: dict | None = None,
    resume: str | None = None,
    real_embeddings: bool = False,
) -> int:
    # resume-parser runs for real when given a PDF; otherwise the stand-in
    # profile keeps the rest of the pipeline runnable without an API key.
    developer = STAND_IN_DEVELOPER
    if resume:
        developer = parse_resume(resume, ClaudeProfileExtractor())

    state = SessionState(user_id="local", developer_context=developer)
    state.interview_context = conduct_interview(
        state.developer_context, answers or STAND_IN_ANSWERS
    )

    async with GitHubClient() as client:
        state.repo_facts = await investigate(repo, client)
        state.vibe_summary = await check_vibe(state.repo_facts, client)
        state.setup_steps = await validate_setup(state.repo_facts, client)

    embeddings, is_semantic = build_embeddings(real_embeddings)
    state.top_match, filters, ranked = match_issues(
        state.developer_context,
        state.interview_context,
        state.repo_facts,
        embeddings=embeddings,
    )
    state.roadmap = generate_roadmap(
        developer_context=state.developer_context,
        interview_context=state.interview_context,
        repo_facts=state.repo_facts,
        setup_steps=state.setup_steps,
        vibe_summary=state.vibe_summary,
        top_match=state.top_match,
    )

    print(state.roadmap)
    print()
    print("-" * 72)

    problems = verify_roadmap(state.roadmap)
    lines = len(state.roadmap.splitlines())
    print(f"lines            : {lines}/60")
    print(f"verifier         : {problems if problems else 'clean'}")
    print(f"candidate issues : {len(state.repo_facts.good_first_issues)}")
    print(f"filters applied  : {filters or 'none'}")
    print(f"ranked           : {len(ranked)}")
    if state.top_match:
        print(
            f"top match        : #{state.top_match.issue_id} "
            f"score={state.top_match.score} confident={is_confident(state.top_match)}"
        )
        print(f"  breakdown      : {state.top_match.score_breakdown}")
    else:
        best = ranked[0].score if ranked else None
        print(f"top match        : none (best was {best}, floor is {MINIMUM_SCORE})")
        if not is_semantic:
            print(
                "                   ^ the stand-in embedder is not semantic, so this "
                "says nothing about the repo. Re-run with --real-embeddings."
            )
    print(f"toolchain        : {state.setup_steps.package_manager or 'not detected'}")
    print(f"embedder         : {embeddings.model_id}{'' if is_semantic else '  (not semantic)'}")
    print(f"session state    : {len(state.model_dump_json())} bytes")
    return 1 if problems else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", help="owner/name or a GitHub URL")
    parser.add_argument(
        "--resume", help="path to a PDF resume; runs resume-parser for real (needs an API key)"
    )
    parser.add_argument(
        "--real-embeddings",
        action="store_true",
        help="rank with sentence-transformers rather than the stand-in "
        '(needs the "embeddings" extra)',
    )
    args = parser.parse_args()

    if not os.environ.get("GITHUB_TOKEN"):
        print(
            "GITHUB_TOKEN is not set. Unauthenticated requests are capped at 60/hour,\n"
            "which this pipeline exceeds. Try: GITHUB_TOKEN=$(gh auth token)",
            file=sys.stderr,
        )
        return 2

    try:
        return asyncio.run(run(args.repo, resume=args.resume, real_embeddings=args.real_embeddings))
    except PipelineError as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
