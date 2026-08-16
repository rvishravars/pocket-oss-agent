"""Pipeline errors.

`AGENTS.md` requires agents to fail loudly: a missing or unreachable upstream
input aborts with a descriptive error rather than silently defaulting. Every
exception here names what was missing and, where relevant, what to do about it.
"""


class PipelineError(Exception):
    """Base class for every Pocket OSS Agent failure."""


class MissingUpstreamOutput(PipelineError):
    """A required session-state key was absent when an agent ran."""

    def __init__(self, agent: str, key: str) -> None:
        super().__init__(
            f"{agent} requires session state key '{key}', which is not set. "
            f"Run the upstream agent that produces it before this one."
        )
        self.agent = agent
        self.key = key


class IncompleteInterview(PipelineError):
    """A mandatory interview category was unanswered."""

    def __init__(self, missing: list[str]) -> None:
        names = ", ".join(sorted(missing))
        super().__init__(
            f"Interview is missing required answers for: {names}. "
            f"Re-prompt for these rather than assuming a default, since they "
            f"drive issue filtering and roadmap tone."
        )
        self.missing = sorted(missing)


class UnknownInterviewAnswer(PipelineError):
    """An answer did not match any option in its category."""

    def __init__(self, category: str, value: str, allowed: list[str]) -> None:
        super().__init__(
            f"{value!r} is not a valid answer for interview category "
            f"{category!r}. Expected one of: {', '.join(sorted(allowed))}."
        )
        self.category = category
        self.value = value


class ResumeUnreadable(PipelineError):
    """A resume could not be turned into usable text."""

    def __init__(self, source: str, reason: str) -> None:
        super().__init__(f"Could not read a resume from {source!r}: {reason}")
        self.source = source
        self.reason = reason


class ProfileExtractionFailed(PipelineError):
    """The model did not return a usable profile."""

    def __init__(self, reason: str, detail: str = "") -> None:
        suffix = f" ({detail})" if detail else ""
        super().__init__(f"Profile extraction failed: {reason}{suffix}.")
        self.reason = reason
        self.detail = detail


class RepoAnalysisFailed(PipelineError):
    """The model did not return a usable repository analysis."""

    def __init__(self, reason: str, detail: str = "") -> None:
        suffix = f" ({detail})" if detail else ""
        super().__init__(f"Repo analysis failed: {reason}{suffix}.")
        self.reason = reason
        self.detail = detail


class EmbeddingModelMismatch(PipelineError):
    """A store and an embedding provider disagree on the model.

    Vectors from two models occupy unrelated spaces, so comparing them yields
    confident, meaningless scores that nothing downstream can detect. This is
    the check `AGENTS.md` requires.
    """

    def __init__(self, store: str, provider: str) -> None:
        super().__init__(
            f"Vector store was built with embedding model {store!r} but the provider "
            f"is {provider!r}. Comparing vectors across models produces meaningless "
            f"similarity scores. Re-embed the store, or use the matching provider."
        )
        self.store = store
        self.provider = provider


class InvalidRepoURL(PipelineError):
    """The supplied string is not a GitHub repository URL."""

    def __init__(self, url: str) -> None:
        super().__init__(
            f"Could not parse a GitHub owner/repo from {url!r}. "
            f"Expected something like https://github.com/owner/repo."
        )
        self.url = url


class RepositoryUnavailable(PipelineError):
    """The repository does not exist, or the token cannot see it."""

    def __init__(self, owner: str, repo: str) -> None:
        super().__init__(
            f"Repository {owner}/{repo} is not accessible. It may not exist, or it "
            f"may be private and outside the scope of GITHUB_TOKEN."
        )
        self.owner = owner
        self.repo = repo


class NetworkUnavailable(PipelineError):
    """GitHub could not be reached: timeout, DNS failure, connection reset.

    Mapped so the client presents one failure surface. Without this a caller
    catching `PipelineError` still crashes on a raw httpx exception, which is
    exactly the case a long concurrent fan-out is most likely to hit.
    """

    def __init__(self, path: str, cause: Exception) -> None:
        super().__init__(
            f"Could not reach GitHub for {path}: {type(cause).__name__}. "
            f"This is usually transient; retry before treating it as a failure."
        )
        self.path = path
        self.cause = cause


class RateLimited(PipelineError):
    """The GitHub API rejected the request for rate-limiting reasons."""

    def __init__(self, reset_epoch: int | None = None) -> None:
        detail = f" Limit resets at epoch {reset_epoch}." if reset_epoch else ""
        super().__init__(f"GitHub API rate limit exceeded.{detail}")
        self.reset_epoch = reset_epoch
