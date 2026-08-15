#!/usr/bin/env python3
"""Run the implemented agents against a real repository and print the roadmap.

Every significant bug in this codebase passed its mocked tests first. Mocks
confirm the code does what you assumed; only live data challenges the
assumption. This is the harness for that check.

    GITHUB_TOKEN=$(gh auth token) python scripts/run_pipeline.py pallets/flask

`resume-parser` and `skill-matcher` are not built yet, so their outputs are
stand-ins, marked below. Everything else is the real agent.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from pocket_oss_agent.agents.env_validator import validate_setup
from pocket_oss_agent.agents.interviewer import conduct_interview
from pocket_oss_agent.agents.repo_investigator import investigate
from pocket_oss_agent.agents.strategy_generator import generate_roadmap, verify_roadmap
from pocket_oss_agent.agents.vibe_checker import check_vibe
from pocket_oss_agent.errors import PipelineError
from pocket_oss_agent.github_client import GitHubClient
from pocket_oss_agent.state import DeveloperContext, SessionState, TopMatch

# --- stand-ins for the two unbuilt agents ------------------------------------

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


def stand_in_top_match(repo_facts) -> TopMatch | None:
    """What `skill-matcher` will eventually choose.

    Takes the freshest candidate rather than ranking, so the roadmap has
    something real to render. Returns None when the repo labels nothing, which
    exercises the browse-manually fallback.
    """
    if not repo_facts.good_first_issues:
        return None
    issue = repo_facts.good_first_issues[0]
    return TopMatch(
        issue_id=issue.id,
        title=issue.title,
        url=issue.url,
        score=0.81,
        rationale=(
            "You have 5 years of Python experience. Matches your stated goal at your stated pace."
        ),
    )


# --- pipeline ----------------------------------------------------------------


async def run(repo: str, *, answers: dict | None = None) -> int:
    state = SessionState(user_id="local", developer_context=STAND_IN_DEVELOPER)
    state.interview_context = conduct_interview(
        state.developer_context, answers or STAND_IN_ANSWERS
    )

    async with GitHubClient() as client:
        state.repo_facts = await investigate(repo, client)
        state.vibe_summary = await check_vibe(state.repo_facts, client)
        state.setup_steps = await validate_setup(state.repo_facts, client)

    state.top_match = stand_in_top_match(state.repo_facts)
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
    print(f"toolchain        : {state.setup_steps.package_manager or 'not detected'}")
    print(f"session state    : {len(state.model_dump_json())} bytes")
    return 1 if problems else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", help="owner/name or a GitHub URL")
    args = parser.parse_args()

    if not os.environ.get("GITHUB_TOKEN"):
        print(
            "GITHUB_TOKEN is not set. Unauthenticated requests are capped at 60/hour,\n"
            "which this pipeline exceeds. Try: GITHUB_TOKEN=$(gh auth token)",
            file=sys.stderr,
        )
        return 2

    try:
        return asyncio.run(run(args.repo))
    except PipelineError as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
