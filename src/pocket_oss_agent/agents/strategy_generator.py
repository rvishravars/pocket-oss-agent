"""contribution-strategy-generator: weave every upstream output into the roadmap.

Implements `specs/agents/contribution-strategy-generator.md`. Terminal node of
the pipeline, producing the one-page Markdown document the product exists to
deliver.

The spec lists an LLM as the tooling, but the work is deterministic assembly:
every sentence is composed from structured upstream fields. Templating it keeps
the output reproducible, keeps the line budget enforceable, and removes any
chance of the final step inventing a fact that no agent established.
"""

from __future__ import annotations

from ..errors import MissingUpstreamOutput
from ..state import (
    DeveloperContext,
    InterviewContext,
    RepoFacts,
    SetupSteps,
    TopMatch,
    VibeSummary,
)

MAX_ROADMAP_LINES = 60
MAX_ARCHITECTURE_BULLETS = 5
MAX_SETUP_STEPS = 10
MAX_FALLBACK_ISSUES = 3
ELLIPSIS = "…"

STATUS_MARKS = {"validated": "✅", "unverified": "⚠️"}

COMMIT_BADGES = {
    "actively_maintained": "🟢",
    "moderate_activity": "🟡",
    "slowing_down": "🟠",
    "potentially_dormant": "🔴",
    "unknown": "⚪",
}

GOAL_LABELS = {
    "learning": "learning",
    "portfolio": "portfolio",
    "professional": "professional use",
    "career": "career",
    "altruism": "giving back",
}

TIME_LABELS = {"light": "light (~5 hrs/week)", "moderate": "5-15 hrs/week", "heavy": "15+ hrs/week"}

#: Rough wall-clock estimates, matched by command prefix. Shown only when the
#: developer reported light availability, where knowing a step costs minutes
#: rather than an evening is what decides whether they start at all.
STEP_ESTIMATES: tuple[tuple[str, str], ...] = (
    ("git clone", "~1 min"),
    ("cd ", "instant"),
    ("cp ", "~1 min"),
    ("docker compose", "~3 min"),
    ("docker-compose", "~3 min"),
    ("make install", "~2 min"),
    ("make test", "~2 min"),
)
DEFAULT_ESTIMATE = "~2 min"


def generate_roadmap(
    *,
    developer_context: DeveloperContext | None,
    interview_context: InterviewContext | None,
    repo_facts: RepoFacts | None,
    setup_steps: SetupSteps | None,
    vibe_summary: VibeSummary | None,
    top_match: TopMatch | None,
) -> str:
    """Assemble the one-page roadmap.

    Aborts naming the first missing required input. `top_match` is the single
    permitted null, and only because `skill-matcher` may legitimately find
    nothing above its threshold; that case renders a browse-manually fallback
    rather than dropping the section.
    """
    required = {
        "developer_context": developer_context,
        "interview_context": interview_context,
        "repo_facts": repo_facts,
        "setup_steps": setup_steps,
        "vibe_summary": vibe_summary,
    }
    for key, value in required.items():
        if value is None:
            raise MissingUpstreamOutput(agent="contribution-strategy-generator", key=key)

    assert developer_context and interview_context and repo_facts
    assert setup_steps and vibe_summary

    blocks = [
        _header(developer_context, interview_context, repo_facts),
        _architecture_section(repo_facts),
        _setup_section(setup_steps, interview_context),
        _target_section(top_match, interview_context, repo_facts),
        _vibe_section(vibe_summary),
    ]

    lines: list[str] = []
    for block in blocks:
        if lines:
            lines.append("")
        lines.extend(block)

    return "\n".join(_enforce_line_budget(lines))


def _header(developer: DeveloperContext, interview: InterviewContext, repo: RepoFacts) -> list[str]:
    lines = [f"# OSS Contribution Roadmap: {repo.slug}"]

    descriptor = " ".join(part for part in (developer.seniority, developer.domain) if part)
    if developer.name and descriptor:
        lines.append(f"> Generated for {developer.name} · {descriptor} engineer")
    elif developer.name:
        lines.append(f"> Generated for {developer.name}")
    elif descriptor:
        lines.append(f"> {descriptor.capitalize()} engineer")

    goal = GOAL_LABELS.get(interview.goal, interview.goal)
    availability = TIME_LABELS.get(interview.time_commitment, interview.time_commitment)
    lines.append(f"> 🎯 Goal: {goal} · ⏱️ Availability: {availability}")
    return lines


def _architecture_section(repo: RepoFacts) -> list[str]:
    lines = ["## 🗺️ Architecture Snapshot"]
    if not repo.architecture_snapshot:
        lines.append(
            "- Layout not auto-detected. This repo nests its code, so start from the README."
        )
        return lines

    entries = list(repo.architecture_snapshot.items())
    for path, description in entries[:MAX_ARCHITECTURE_BULLETS]:
        lines.append(f"- `{path}/` - {description}")
    if len(entries) > MAX_ARCHITECTURE_BULLETS:
        lines.append(f"- {ELLIPSIS} and {len(entries) - MAX_ARCHITECTURE_BULLETS} more")
    return lines


def _setup_section(setup: SetupSteps, interview: InterviewContext) -> list[str]:
    lines = ["## 🚀 First Mile Setup"]
    if not setup.setup_steps:
        lines.append("1. No setup detected. Follow CONTRIBUTING.md.")
        return lines

    show_estimates = interview.time_commitment == "light"
    for index, step in enumerate(setup.setup_steps[:MAX_SETUP_STEPS], start=1):
        mark = STATUS_MARKS.get(step.status, "")
        estimate = f" _{_estimate_for(step.command)}_" if show_estimates else ""
        lines.append(f"{index}. `{step.command}` {mark}{estimate}".rstrip())

    remaining = len(setup.setup_steps) - MAX_SETUP_STEPS
    if remaining > 0:
        lines.append(f"{ELLIPSIS} and {remaining} more")

    if setup.package_manager is None:
        # Detection reads root files only, so a monorepo nesting its manifests
        # yields a clone-and-cd guide. Saying so beats presenting two steps as
        # though they were the whole setup.
        lines.append("> No toolchain detected at the repo root. See CONTRIBUTING.md to install.")
    elif any(step.status == "unverified" for step in setup.setup_steps[:MAX_SETUP_STEPS]):
        lines.append("> ⚠️ Steps are inferred from config files, not yet executed.")
    return lines


def _target_section(
    top_match: TopMatch | None, interview: InterviewContext, repo: RepoFacts
) -> list[str]:
    lines = ["## 🎯 Your First Contribution"]

    if top_match is None:
        if repo.good_first_issues:
            lines.append("No strong match found. These beginner-friendly issues are open now:")
            for issue in repo.good_first_issues[:MAX_FALLBACK_ISSUES]:
                lines.append(f"- [{issue.title}]({issue.url})")
        else:
            lines.append(
                f"This repo labels no beginner-friendly issues. Open an issue on "
                f"[{repo.slug}](https://github.com/{repo.slug}/issues) asking where to start."
            )
        return lines

    if interview.risk_tolerance == "low":
        lines.append("_Picked to sit close to what you already know._")

    lines.append(f"**Issue:** [{top_match.title}]({top_match.url})")
    lines.append(f"**Why you:** {top_match.rationale}")

    if interview.goal == "learning":
        lines.append("**What you'll learn:** the codebase area this issue touches, hands on.")
    elif interview.goal == "career":
        lines.append("**How this helps:** a merged PR here is public, checkable evidence.")
    return lines


def _vibe_section(vibe: VibeSummary) -> list[str]:
    badge = COMMIT_BADGES.get(vibe.commit_status, "")
    lines = ["## 💬 Vibe Check", f"{badge} {vibe.vibe_summary}".strip()]

    if vibe.pr_merge_rate is not None and vibe.pr_merge_rate < 0.70:
        lines.append(
            f"> Only {vibe.pr_merge_rate:.0%} of closed PRs get merged here. "
            f"Common for busy projects, but worth agreeing an approach on the issue first."
        )
    return lines


def _estimate_for(command: str) -> str:
    for prefix, estimate in STEP_ESTIMATES:
        if command.startswith(prefix):
            return estimate
    return DEFAULT_ESTIMATE


def _enforce_line_budget(lines: list[str]) -> list[str]:
    """Keep the document inside one screen.

    Section builders are individually capped, so this is a backstop rather than
    the primary control. It trims from the end and marks the cut, since dropping
    a whole section is forbidden and a silently truncated document is worse than
    a visibly truncated one.
    """
    if len(lines) <= MAX_ROADMAP_LINES:
        return lines
    kept = lines[: MAX_ROADMAP_LINES - 1]
    kept.append(f"{ELLIPSIS} truncated to fit one screen")
    return kept


def verify_roadmap(roadmap: str) -> list[str]:
    """Return spec violations, empty when the document is well formed."""
    problems: list[str] = []
    lines = roadmap.splitlines()

    for heading in (
        "## 🗺️ Architecture Snapshot",
        "## 🚀 First Mile Setup",
        "## 🎯 Your First Contribution",
        "## 💬 Vibe Check",
    ):
        if heading not in roadmap:
            problems.append(f"missing section: {heading}")

    if len(lines) > MAX_ROADMAP_LINES:
        problems.append(f"{len(lines)} lines exceeds the {MAX_ROADMAP_LINES} line budget")
    if not lines or not lines[0].startswith("# OSS Contribution Roadmap:"):
        problems.append("missing roadmap title")
    if "🎯 Goal:" not in roadmap or "⏱️ Availability:" not in roadmap:
        problems.append("header must carry both goal and availability")

    for line in lines:
        if "](" in line and "](https://" not in line:
            problems.append(f"link is not an https URL: {line.strip()}")
    return problems
