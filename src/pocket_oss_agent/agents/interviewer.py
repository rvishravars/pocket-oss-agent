"""interviewer-agent: capture contribution intent that a resume cannot show.

Implements `specs/agents/interviewer-agent.md`. Consumes `developer_context`
and produces `interview_context`.

The spec names a UI chat or form flow as the tooling, but that is the delivery
layer. Everything here is headless: `QUESTION_BANK` is data a UI renders, and
`conduct_interview` turns the answers it posts back into a validated
`InterviewContext`. Keeping it that way means the pipeline logic is testable
without a browser, and a chat client, a web form and a CLI can all drive it.
"""

from __future__ import annotations

from typing import NamedTuple

from ..errors import IncompleteInterview, MissingUpstreamOutput, UnknownInterviewAnswer
from ..state import DeveloperContext, InterviewContext

MAX_SUMMARY_WORDS = 30
MAX_TYPES_IN_SUMMARY = 2


class Option(NamedTuple):
    """One selectable answer. `value` is what a UI posts back."""

    value: str
    label: str


class Category(NamedTuple):
    """One interview question."""

    key: str
    prompt: str
    options: tuple[Option, ...]
    required: bool = True
    multi_select: bool = False
    default: str | None = None

    @property
    def values(self) -> list[str]:
        return [option.value for option in self.options]


QUESTION_BANK: tuple[Category, ...] = (
    Category(
        key="goal",
        prompt="What's your primary goal for contributing to this project?",
        options=(
            Option("learning", "Learn new skills / explore the codebase"),
            Option("portfolio", "Build portfolio / showcase work"),
            Option("professional", "Support a project I use professionally"),
            Option("career", "Land a job at this company"),
            Option("altruism", "Give back to open source"),
        ),
    ),
    Category(
        key="time_commitment",
        prompt="How much time can you commit per week?",
        options=(
            Option("light", "A few hours (< 5 hrs/week)"),
            Option("moderate", "Part-time (5-15 hrs/week)"),
            Option("heavy", "Near full-time (15+ hrs/week)"),
        ),
    ),
    Category(
        key="contribution_types",
        prompt="What type of contribution are you most comfortable starting with?",
        options=(
            Option("bugfix", "Bug fixes"),
            Option("docs", "Documentation"),
            Option("feature", "New features"),
            Option("tests", "Tests / code coverage"),
            Option("refactor", "Performance / refactoring"),
            Option("any", "Any, surprise me"),
        ),
        multi_select=True,
    ),
    Category(
        key="risk_tolerance",
        prompt="How do you feel about tackling unfamiliar code areas?",
        options=(
            Option("low", "Stay in my comfort zone only"),
            Option("medium", "Some stretch is fine"),
            Option("high", "Challenge me"),
        ),
    ),
    Category(
        key="collaboration_style",
        prompt="Do you prefer issues where you work solo or ones with active discussion?",
        options=(
            Option("solo", "Solo, I'll figure it out"),
            Option("guided", "Active thread, I want guidance"),
            Option("any", "No preference"),
        ),
        required=False,
        default="any",
    ),
)

CATEGORIES = {category.key: category for category in QUESTION_BANK}

GOAL_PHRASES = {
    "learning": "learn new skills",
    "portfolio": "build their portfolio",
    "professional": "support a project they rely on at work",
    "career": "land a job at this company",
    "altruism": "give back to open source",
}
TIME_PHRASES = {"light": "~5 hrs/week", "moderate": "5-15 hrs/week", "heavy": "15+ hrs/week"}
TYPE_PHRASES = {
    "bugfix": "bug fixes",
    "docs": "documentation",
    "feature": "new features",
    "tests": "tests",
    "refactor": "refactoring",
    "any": "any kind of work",
}
RISK_PHRASES = {
    "low": "staying within familiar territory",
    "medium": "open to some stretch",
    "high": "ready for a challenge",
}


def opening_line(developer_context: DeveloperContext) -> str:
    """Personalize the opening by seniority, per the spec's tone rules."""
    if developer_context.seniority == "junior":
        return (
            "Before we dive in, a few quick questions so I can tailor your roadmap. "
            "There are no wrong answers here."
        )
    if developer_context.seniority in {"senior", "staff"}:
        return "A few quick questions to tailor your roadmap."
    return "Before we dive in, a few quick questions to tailor your roadmap."


def build_intent_summary(
    goal: str, time_commitment: str, contribution_types: list[str], risk_tolerance: str
) -> str:
    """One sentence of intent for the Strategy Generator, at most 30 words.

    Long multi-selects are elided rather than allowed to blow the budget, since
    the header this feeds has a fixed line allowance.
    """
    named = [
        TYPE_PHRASES[t] for t in contribution_types[:MAX_TYPES_IN_SUMMARY] if t in TYPE_PHRASES
    ]
    if len(contribution_types) > MAX_TYPES_IN_SUMMARY:
        named.append("and more")
    types = " and ".join(named) if named else "any kind of work"

    summary = (
        f"Developer wants to {GOAL_PHRASES[goal]} through {types}, "
        f"committing {TIME_PHRASES[time_commitment]}, {RISK_PHRASES[risk_tolerance]}."
    )
    words = summary.split()
    if len(words) > MAX_SUMMARY_WORDS:
        summary = " ".join(words[:MAX_SUMMARY_WORDS]).rstrip(",") + "."
    return summary


def normalise_answer(category: Category, raw: object) -> str | list[str]:
    """Validate one answer against its category, returning the stored form."""
    if category.multi_select:
        values = list(raw) if isinstance(raw, list | tuple | set) else [raw]
        chosen = [str(value) for value in values]
        for value in chosen:
            if value not in category.values:
                raise UnknownInterviewAnswer(category.key, value, category.values)
        return chosen

    value = str(raw)
    if value not in category.values:
        raise UnknownInterviewAnswer(category.key, value, category.values)
    return value


def conduct_interview(
    developer_context: DeveloperContext | None, answers: dict[str, object]
) -> InterviewContext:
    """Turn posted answers into a validated `interview_context`.

    Raises `MissingUpstreamOutput` without a developer context, since question
    phrasing is personalized from it. Raises `IncompleteInterview` when a
    mandatory category is unanswered: the spec treats that as a validation
    error to re-prompt, not something to quietly default, because these answers
    drive issue filtering and roadmap tone.
    """
    if developer_context is None:
        raise MissingUpstreamOutput(agent="interviewer-agent", key="developer_context")

    resolved: dict[str, str | list[str]] = {}
    missing: list[str] = []

    for category in QUESTION_BANK:
        raw = answers.get(category.key)
        if raw is None or raw == [] or raw == "":
            if category.required:
                missing.append(category.key)
            elif category.default is not None:
                resolved[category.key] = category.default
            continue
        resolved[category.key] = normalise_answer(category, raw)

    if missing:
        raise IncompleteInterview(missing)

    goal = str(resolved["goal"])
    time_commitment = str(resolved["time_commitment"])
    contribution_types = list(resolved["contribution_types"])
    risk_tolerance = str(resolved["risk_tolerance"])

    return InterviewContext(
        goal=goal,
        time_commitment=time_commitment,
        contribution_types=contribution_types,
        risk_tolerance=risk_tolerance,
        collaboration_style=str(resolved.get("collaboration_style", "any")),
        intent_summary=build_intent_summary(
            goal, time_commitment, contribution_types, risk_tolerance
        ),
    )
