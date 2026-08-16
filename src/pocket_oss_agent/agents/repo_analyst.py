"""repo-analyst: offline, per-repository synthesis, cached and reused.

Implements `specs/agents/repo-analyst.md`. Consumes `repo_facts` from
`github-repo-investigator`; produces `RepoIntelligence`.

`repo_facts` is deliberately token-budgeted: titles, labels, counts, no issue
bodies, no comment threads, no README text. This agent is where that raw
material actually gets read - and, because reading it is expensive, it runs
once per repository behind `RepoIntelligenceStore` rather than once per user
session. A cache hit makes no GitHub or Claude call at all.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Literal, NamedTuple, Protocol

from pydantic import BaseModel, Field

from ..errors import RepoAnalysisFailed
from ..github_client import GitHubClient
from ..repo_intelligence_store import RepoIntelligenceStore
from ..state import IssueIntelligence, RepoFacts, RepoIntelligence

#: This step reasons across a whole repository's worth of material at once -
#: README, CONTRIBUTING, and up to ten issues each with their own comment
#: thread - and has to weigh conflicting signals (a label says "good first
#: issue"; three comments say it is half-finished by someone else). That is
#: judgment, not single-field extraction, so this is not the tier Haiku is
#: for.
MODEL = "claude-sonnet-5"
MAX_TOKENS = 8_000

#: Kept well under the model's context window even for a repository with the
#: full ten candidate issues, each with a comment thread attached.
MAX_DOC_CHARS = 8_000
MAX_BODY_CHARS = 4_000
MAX_COMMENT_CHARS = 1_000
MAX_COMMENTS_PER_ISSUE = 10

README_CANDIDATES = ("README.md", "Readme.md", "readme.md", "README.rst", "README")
CONTRIBUTING_CANDIDATES = ("CONTRIBUTING.md", "Contributing.md", "contributing.md")

SYSTEM_PROMPT = (
    "You are an experienced open-source maintainer evaluating this repository for a "
    "prospective first-time contributor. Read the README, the CONTRIBUTING guide, and "
    "each candidate issue's body and comment thread. Judge difficulty and required "
    "skills from what the issue and its discussion actually say, not from labels alone. "
    "Read the comment tone to judge how maintainers actually treat contributors - do not "
    "infer this from counts or dates. Report an issue as stale_or_claimed when a comment "
    "shows someone is already assigned to it or has an open pull request against it."
)


class IssueMaterial(NamedTuple):
    """One candidate issue's raw content, gathered for the synthesis call."""

    issue_id: int
    title: str
    labels: list[str]
    body: str
    comments: list[str]


# The class and field docstrings below are sent to the model as the schema
# description, so they are written for the model. Implementation rationale
# belongs in comments, which cost no tokens.
class IssueAnalysis(BaseModel):
    """One candidate issue, read rather than filtered."""

    issue_id: int = Field(description="The issue number, matching the id given in the prompt")
    difficulty: Literal["trivial", "easy", "moderate", "hard"] = Field(
        description="How much unfamiliar-codebase context this issue actually requires"
    )
    skills: list[str] = Field(
        description="Specific skills or technologies this issue actually requires"
    )
    summary: str = Field(
        description="One sentence: what concretely needs to happen to resolve this"
    )
    stale_or_claimed: bool = Field(
        description="True if the issue looks abandoned, or already claimed by someone "
        "actively working on it"
    )


class RepoAnalysis(BaseModel):
    """A synthesized understanding of an open-source repository and its beginner-friendly issues."""

    architecture_summary: str | None = Field(
        description="Two to three sentences on what this codebase does and how it is organized"
    )
    tech_stack: list[str] = Field(
        description="Primary languages, frameworks and tools this project uses"
    )
    contribution_culture: str | None = Field(
        description="One to two sentences on how maintainers actually treat contributors, "
        "from the issue and comment tone given"
    )
    issues: list[IssueAnalysis] = Field(
        description="One entry per candidate issue given, covering every issue id in the prompt"
    )

    def to_repo_intelligence(self, repo_slug: str, model_id: str) -> RepoIntelligence:
        return RepoIntelligence(
            repo_slug=repo_slug,
            architecture_summary=self.architecture_summary,
            tech_stack=self.tech_stack,
            contribution_culture=self.contribution_culture,
            issues=[
                IssueIntelligence(
                    issue_id=issue.issue_id,
                    difficulty=issue.difficulty,
                    skills=issue.skills,
                    summary=issue.summary,
                    stale_or_claimed=issue.stale_or_claimed,
                )
                for issue in self.issues
            ],
            model_id=model_id,
            computed_at=datetime.now(UTC),
        )


class RepoAnalyzer(Protocol):
    """Synthesizes gathered repository material into `RepoIntelligence`."""

    def analyze(
        self,
        repo_facts: RepoFacts,
        readme_text: str | None,
        contributing_text: str | None,
        issues: list[IssueMaterial],
    ) -> RepoIntelligence: ...


class ClaudeRepoAnalyzer:
    """Synthesizes a repository analysis with one structured-output call to Claude."""

    def __init__(self, client=None, model: str = MODEL, max_tokens: int = MAX_TOKENS) -> None:
        if client is None:
            import anthropic  # imported lazily so the package works without a key

            client = anthropic.Anthropic()
        self._client = client
        self._model = model
        self._max_tokens = max_tokens

    def analyze(
        self,
        repo_facts: RepoFacts,
        readme_text: str | None,
        contributing_text: str | None,
        issues: list[IssueMaterial],
    ) -> RepoIntelligence:
        response = self._client.messages.parse(
            model=self._model,
            max_tokens=self._max_tokens,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": _build_prompt(repo_facts, readme_text, contributing_text, issues),
                }
            ],
            output_format=RepoAnalysis,
        )

        # Check stop_reason before touching content. A refusal returns HTTP 200
        # with empty or partial content, so reading parsed_output first turns a
        # policy decline into an unrelated AttributeError.
        stop_reason = getattr(response, "stop_reason", None)
        if stop_reason == "refusal":
            raise RepoAnalysisFailed(
                "the model declined to analyze this repository",
                detail=_refusal_detail(response),
            )
        if stop_reason == "max_tokens":
            raise RepoAnalysisFailed(
                "the response hit the token ceiling before the analysis was complete",
                detail=f"raise max_tokens above {self._max_tokens}",
            )

        analysis = getattr(response, "parsed_output", None)
        if analysis is None:
            raise RepoAnalysisFailed(
                "the response carried no parsed analysis",
                detail=f"stop_reason was {stop_reason!r}",
            )

        intelligence = analysis.to_repo_intelligence(repo_facts.slug, self._model)

        # A partial result is worse than an honest failure: a consumer has no
        # way to tell "not analyzed" from "analyzed, nothing notable."
        expected_ids = {issue.issue_id for issue in issues}
        actual_ids = {issue.issue_id for issue in intelligence.issues}
        if expected_ids != actual_ids:
            raise RepoAnalysisFailed(
                "the analysis did not cover every candidate issue",
                detail=f"expected {sorted(expected_ids)}, got {sorted(actual_ids)}",
            )

        return intelligence


def _build_prompt(
    repo_facts: RepoFacts,
    readme_text: str | None,
    contributing_text: str | None,
    issues: list[IssueMaterial],
) -> str:
    parts = [f"Repository: {repo_facts.slug}"]
    if repo_facts.root_files:
        parts.append(f"Root files: {', '.join(repo_facts.root_files)}")
    if readme_text:
        parts.append(f"\n## README\n{readme_text}")
    if contributing_text:
        parts.append(f"\n## CONTRIBUTING\n{contributing_text}")

    if not issues:
        parts.append("\nNo candidate issues were found for this repository.")
        return "\n".join(parts)

    parts.append("\n## Candidate issues")
    for issue in issues:
        parts.append(f"\n### Issue #{issue.issue_id}: {issue.title}")
        parts.append(f"Labels: {', '.join(issue.labels) or 'none'}")
        parts.append(f"Body:\n{issue.body or '(no body)'}")
        if issue.comments:
            parts.append("Comments:")
            parts.extend(f"- {comment}" for comment in issue.comments)
    return "\n".join(parts)


def _refusal_detail(response: object) -> str:
    details = getattr(response, "stop_details", None)
    category = getattr(details, "category", None)
    return f"refusal category: {category}" if category else "no category reported"


async def _fetch_doc(
    client: GitHubClient, owner: str, repo: str, candidates: tuple[str, ...], root_files: list[str]
) -> str | None:
    """Return the first candidate filename present in `root_files` that reads back non-empty."""
    present = set(root_files)
    for name in candidates:
        if name not in present:
            continue
        text = await client.get_file_text(owner, repo, name)
        if text:
            return text[:MAX_DOC_CHARS]
    return None


async def _fetch_issue_material(
    client: GitHubClient, owner: str, repo: str, issue_id: int, title: str, labels: list[str]
) -> IssueMaterial:
    record, comments = await asyncio.gather(
        client.get_issue(owner, repo, issue_id),
        client.list_issue_comments(owner, repo, issue_id, per_page=MAX_COMMENTS_PER_ISSUE),
    )
    body = (record.get("body") or "") if record else ""
    return IssueMaterial(
        issue_id=issue_id,
        title=title,
        labels=labels,
        body=body[:MAX_BODY_CHARS],
        comments=[
            str(comment.get("body", ""))[:MAX_COMMENT_CHARS]
            for comment in comments
            if isinstance(comment, dict) and comment.get("body")
        ],
    )


async def analyze_repo(
    repo_facts: RepoFacts,
    client: GitHubClient,
    analyzer: RepoAnalyzer,
    store: RepoIntelligenceStore,
) -> RepoIntelligence:
    """Return this repository's `RepoIntelligence`, computing it only on a cache miss.

    The cache check happens before any GitHub or Claude call, not after: the
    whole point of running this offline is that a popular repository is
    analyzed once, not once per contributor who asks about it.
    """
    cached = store.get(repo_facts.slug)
    if cached is not None:
        return cached

    owner, repo = repo_facts.owner, repo_facts.repo
    readme_text, contributing_text, issue_materials = await asyncio.gather(
        _fetch_doc(client, owner, repo, README_CANDIDATES, repo_facts.root_files),
        _fetch_doc(client, owner, repo, CONTRIBUTING_CANDIDATES, repo_facts.root_files),
        asyncio.gather(
            *(
                _fetch_issue_material(client, owner, repo, issue.id, issue.title, issue.labels)
                for issue in repo_facts.good_first_issues
            )
        ),
    )

    intelligence = analyzer.analyze(repo_facts, readme_text, contributing_text, issue_materials)
    store.put(intelligence)
    return intelligence
