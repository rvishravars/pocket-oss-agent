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


class RateLimited(PipelineError):
    """The GitHub API rejected the request for rate-limiting reasons."""

    def __init__(self, reset_epoch: int | None = None) -> None:
        detail = f" Limit resets at epoch {reset_epoch}." if reset_epoch else ""
        super().__init__(f"GitHub API rate limit exceeded.{detail}")
        self.reset_epoch = reset_epoch
