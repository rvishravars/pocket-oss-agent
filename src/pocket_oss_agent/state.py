"""The session state object passed between pipeline agents.

Mirrors the schema in `AGENTS.md`. Each agent reads the keys named in its spec's
`consumes` frontmatter and writes the one named in `produces`.

Only `repo_facts` is exercised today. The rest are defined now so the contract
between agents is fixed before their implementations land, and so a downstream
agent can be built against a fixture without renegotiating field names.
"""

from typing import Literal

from pydantic import BaseModel, Field

from .errors import MissingUpstreamOutput

Seniority = Literal["junior", "mid", "senior", "staff"]
SetupStatus = Literal["validated", "unverified"]


class DeveloperContext(BaseModel):
    """Produced by `resume-parser`."""

    #: The roadmap header greets the developer by name. Optional, because a
    #: resume without a clearly parseable name should still yield a profile
    #: rather than abort; the header drops the greeting instead.
    name: str | None = None
    languages: list[str] = Field(default_factory=list)
    frameworks: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    years_experience: int | None = None
    seniority: Seniority | None = None
    domain: str | None = None


class InterviewContext(BaseModel):
    """Produced by `interviewer-agent`."""

    goal: str
    time_commitment: Literal["light", "moderate", "heavy"]
    contribution_types: list[str] = Field(default_factory=list)
    risk_tolerance: Literal["low", "medium", "high"]
    collaboration_style: Literal["solo", "guided", "any"] | None = None
    intent_summary: str = ""


class GoodFirstIssue(BaseModel):
    """A triaged candidate issue.

    `comment_count` is required rather than optional because `skill-matcher`
    applies its `collab:guided` adjustment from it. Making it nullable here
    would push a None check into every consumer.
    """

    id: int
    title: str
    url: str
    labels: list[str] = Field(default_factory=list)
    days_open: int
    comment_count: int


class RepoFacts(BaseModel):
    """Produced by `github-repo-investigator`.

    Summaries are stored, never raw payloads. The token budget in the spec
    forbids raw file trees or full issue bodies reaching this object.
    """

    owner: str
    repo: str
    readme_summary: str | None = None
    contributing_summary: str | None = None
    architecture_snapshot: dict[str, str] = Field(default_factory=dict)
    #: Names of files and directories at the repository root.
    #: `env-setup-validator` detects the toolchain from these, so preserving
    #: them costs nothing while saving it a second tree fetch. Names only, and
    #: root only, so this stays far inside the token budget.
    root_files: list[str] = Field(default_factory=list)
    good_first_issues: list[GoodFirstIssue] = Field(default_factory=list)
    avg_pr_merge_days: float | None = None

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.repo}"


class SetupStep(BaseModel):
    """One entry in the First Mile setup guide."""

    step: int
    command: str
    status: SetupStatus


class SetupSteps(BaseModel):
    """Produced by `env-setup-validator`."""

    package_manager: str | None = None
    has_docker: bool = False
    docker_services: list[str] = Field(default_factory=list)
    setup_steps: list[SetupStep] = Field(default_factory=list)


class VibeSummary(BaseModel):
    """Produced by `repo-vibe-checker`."""

    commit_recency_days: int
    commit_status: str
    avg_issue_response_days: float | None = None
    response_status: str | None = None
    pr_merge_rate: float | None = None
    welcome_score: int = 0
    welcome_rating: str | None = None
    vibe_summary: str = ""


class TopMatch(BaseModel):
    """Produced by `skill-matcher`."""

    issue_id: int
    title: str
    url: str
    score: float
    score_breakdown: dict[str, float] = Field(default_factory=dict)
    rationale: str = ""


class SessionState(BaseModel):
    """The object threaded through the LangGraph run."""

    user_id: str
    developer_context: DeveloperContext | None = None
    interview_context: InterviewContext | None = None
    repo_facts: RepoFacts | None = None
    vibe_summary: VibeSummary | None = None
    setup_steps: SetupSteps | None = None
    top_match: TopMatch | None = None
    roadmap: str | None = None

    def require(self, agent: str, key: str):
        """Return a required upstream value, or abort naming what is missing.

        `top_match` is deliberately not special-cased here. It is nullable by
        contract when `skill-matcher` finds nothing above threshold, so its only
        consumer checks for None directly instead of calling this.
        """
        value = getattr(self, key, None)
        if value is None:
            raise MissingUpstreamOutput(agent=agent, key=key)
        return value
