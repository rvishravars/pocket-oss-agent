"""Stand-in outputs for the agents that are not built yet.

`resume-parser` and `skill-matcher` need Postgres, pgvector and an LLM, so their
outputs are fixtures for now. Keeping them here rather than inline in tests means
the day those agents land, the fixtures can be replaced in one place and every
downstream test keeps its meaning.
"""

from pocket_oss_agent.state import (
    DeveloperContext,
    GoodFirstIssue,
    InterviewContext,
    RepoFacts,
    SetupStep,
    SetupSteps,
    TopMatch,
    VibeSummary,
)


def developer_context(**overrides) -> DeveloperContext:
    """Stands in for `resume-parser`."""
    defaults = dict(
        name="Ada Okafor",
        languages=["Python", "Go"],
        frameworks=["FastAPI", "Django"],
        tools=["Docker", "AWS"],
        years_experience=5,
        seniority="mid",
        domain="backend",
    )
    return DeveloperContext(**{**defaults, **overrides})


def interview_context(**overrides) -> InterviewContext:
    defaults = dict(
        goal="portfolio",
        time_commitment="light",
        contribution_types=["bugfix", "docs"],
        risk_tolerance="low",
        collaboration_style="guided",
        intent_summary=(
            "Developer wants to build their portfolio through bug fixes and documentation, "
            "committing ~5 hrs/week, staying within familiar territory."
        ),
    )
    return InterviewContext(**{**defaults, **overrides})


def top_match(**overrides) -> TopMatch:
    """Stands in for `skill-matcher`."""
    defaults = dict(
        issue_id=1234,
        title="Add support for an async Python client",
        url="https://github.com/octo/widget/issues/1234",
        score=0.87,
        score_breakdown={
            "semantic_similarity": 0.74,
            "language_boost": 0.10,
            "interview_type_boost": 0.08,
            "risk_penalty": 0.0,
            "collab_boost": 0.05,
        },
        rationale=(
            "You have 5 years of Python experience with asyncio. Matches your goal to build "
            "a portfolio with lightweight fixes at ~5 hrs/week."
        ),
    )
    return TopMatch(**{**defaults, **overrides})


def repo_facts(**overrides) -> RepoFacts:
    defaults = dict(
        owner="octo",
        repo="widget",
        architecture_snapshot={
            "src": "Core library code",
            "tests": "Unit and integration tests",
            "docs": "Documentation",
        },
        root_files=["Dockerfile", "README.md", "pyproject.toml", "uv.lock"],
        good_first_issues=[
            GoodFirstIssue(
                id=1234,
                title="Add support for an async Python client",
                url="https://github.com/octo/widget/issues/1234",
                labels=["good first issue", "python"],
                days_open=6,
                comment_count=3,
            ),
            GoodFirstIssue(
                id=1240,
                title="Document the retry policy",
                url="https://github.com/octo/widget/issues/1240",
                labels=["documentation"],
                days_open=2,
                comment_count=1,
            ),
        ],
        avg_pr_merge_days=4.2,
    )
    return RepoFacts(**{**defaults, **overrides})


def setup_steps(**overrides) -> SetupSteps:
    defaults = dict(
        package_manager="uv",
        has_docker=True,
        docker_services=["db", "redis"],
        setup_steps=[
            SetupStep(
                step=1, command="git clone https://github.com/octo/widget", status="unverified"
            ),
            SetupStep(step=2, command="cd widget", status="unverified"),
            SetupStep(step=3, command="uv sync", status="unverified"),
            SetupStep(step=4, command="docker compose up -d", status="unverified"),
            SetupStep(step=5, command="uv run pytest", status="unverified"),
        ],
    )
    return SetupSteps(**{**defaults, **overrides})


def vibe_summary(**overrides) -> VibeSummary:
    defaults = dict(
        commit_recency_days=2,
        commit_status="actively_maintained",
        avg_issue_response_days=1.3,
        response_status="very_responsive",
        pr_merge_rate=0.78,
        welcome_score=4,
        welcome_rating="welcoming",
        vibe_summary=(
            "This repo is actively maintained (last commit 2 days ago) and maintainers reply "
            "to issues in about 1.3 days. There are 2 open beginner-friendly issues, and 78% "
            "of recently closed PRs were merged. Overall vibe: welcoming (4/4 welcome signals)."
        ),
    )
    return VibeSummary(**{**defaults, **overrides})
