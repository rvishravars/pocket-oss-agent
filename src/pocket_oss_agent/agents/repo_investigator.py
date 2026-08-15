"""github-repo-investigator: build a repo fact sheet from a repository URL.

Implements steps 1, 3, 4 and 5 of `specs/agents/github-repo-investigator.md`.
Step 2 (README and CONTRIBUTING summarization) needs an LLM and is deferred, so
`readme_summary` and `contributing_summary` stay None for now.

The spec's token budget is the load-bearing constraint here: raw trees and issue
bodies are reduced inside this module and never reach `RepoFacts`.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from ..errors import InvalidRepoURL
from ..github_client import GitHubClient
from ..state import GoodFirstIssue, RepoFacts

TRIAGE_LABELS = ("good first issue", "help wanted", "beginner")
ACTIVITY_WINDOW_DAYS = 90
MAX_CANDIDATE_ISSUES = 10
MAX_MERGED_PULLS = 20
SLOW_MOVING_MERGE_DAYS = 30

#: Directories the Architecture Snapshot reports on, with their descriptions.
KNOWN_DIRECTORIES = {
    "src": "Core library code",
    "lib": "Core library code",
    "tests": "Unit and integration tests",
    "test": "Unit and integration tests",
    "docs": "Documentation",
    "examples": "Usage examples",
}

_URL_PATTERN = re.compile(
    r"""
    ^(?:https?://)?             # optional scheme
    (?:www\.)?
    (?:github\.com[:/])?        # optional host, ':' covers git@github.com:
    (?P<owner>[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)
    /
    (?P<repo>[A-Za-z0-9._-]+?)
    (?:\.git)?                  # optional .git suffix
    /?$
    """,
    re.VERBOSE,
)


def parse_repo_url(url: str) -> tuple[str, str]:
    """Extract ``(owner, repo)`` from a GitHub URL or ``owner/repo`` shorthand.

    Accepts the forms users actually paste: full https URLs, scp-style git
    remotes, a trailing ``.git`` or slash, and the bare shorthand.
    """
    candidate = (url or "").strip()
    candidate = candidate.removeprefix("git@")
    match = _URL_PATTERN.match(candidate)
    if not match:
        raise InvalidRepoURL(url)
    return match.group("owner"), match.group("repo")


def build_architecture_snapshot(tree: list[dict[str, Any]]) -> dict[str, str]:
    """Reduce a raw git tree to the recognised top-level directories.

    The full tree is discarded here. Only matched directory names and their
    fixed descriptions survive into `RepoFacts`.
    """
    snapshot: dict[str, str] = {}
    for entry in tree:
        if entry.get("type") != "tree":
            continue
        path = entry.get("path", "")
        if "/" in path:
            continue  # top level only, depth is capped by the spec
        description = KNOWN_DIRECTORIES.get(path.lower())
        if description and path not in snapshot:
            snapshot[path] = description
    return snapshot


def triage_issues(
    issues: list[dict[str, Any]], *, now: datetime | None = None
) -> list[GoodFirstIssue]:
    """Filter to recently active issues and reduce them to the candidate shape.

    Pull requests are dropped: the GitHub issues endpoint returns them too, and
    a PR is not a contribution opportunity for a newcomer. Issue bodies are
    never carried over.
    """
    now = now or datetime.now(UTC)
    candidates: list[GoodFirstIssue] = []

    for issue in issues:
        if issue.get("pull_request") is not None:
            continue

        updated = _parse_timestamp(issue.get("updated_at"))
        created = _parse_timestamp(issue.get("created_at"))
        if updated is None or created is None:
            continue
        if (now - updated).days > ACTIVITY_WINDOW_DAYS:
            continue

        candidates.append(
            GoodFirstIssue(
                id=issue["number"],
                title=issue.get("title", ""),
                url=issue.get("html_url", ""),
                labels=[_label_name(label) for label in issue.get("labels", [])],
                days_open=max((now - created).days, 0),
                comment_count=issue.get("comments", 0),
            )
        )

    candidates.sort(key=lambda c: c.days_open)
    return candidates[:MAX_CANDIDATE_ISSUES]


def average_merge_days(pulls: list[dict[str, Any]]) -> float | None:
    """Mean days from open to merge over the most recent merged PRs.

    Closed-without-merge PRs are excluded; they say something about the project
    but not about how long merging takes. Returns None when nothing merged,
    which the caller reports rather than rendering as a misleading 0.0.
    """
    durations: list[float] = []
    for pull in pulls:
        merged_at = _parse_timestamp(pull.get("merged_at"))
        created_at = _parse_timestamp(pull.get("created_at"))
        if merged_at is None or created_at is None:
            continue
        durations.append((merged_at - created_at).total_seconds() / 86400)
        if len(durations) >= MAX_MERGED_PULLS:
            break

    if not durations:
        return None
    return round(sum(durations) / len(durations), 2)


def is_slow_moving(avg_pr_merge_days: float | None) -> bool:
    """Whether the repo should be flagged slow-moving per the spec threshold."""
    return avg_pr_merge_days is not None and avg_pr_merge_days > SLOW_MOVING_MERGE_DAYS


async def investigate(url: str, client: GitHubClient, *, now: datetime | None = None) -> RepoFacts:
    """Run the investigator and return the repo fact sheet.

    Raises `InvalidRepoURL` for an unparseable URL, and `RepositoryUnavailable`
    or `RateLimited` from the client when GitHub cannot serve the request.
    """
    owner, repo = parse_repo_url(url)

    tree, issue_sets, pulls = await asyncio.gather(
        client.get_tree(owner, repo),
        asyncio.gather(*(client.list_issues(owner, repo, label=label) for label in TRIAGE_LABELS)),
        client.list_merged_pulls(owner, repo),
    )
    issues = _merge_issue_sets(issue_sets)

    return RepoFacts(
        owner=owner,
        repo=repo,
        architecture_snapshot=build_architecture_snapshot(tree),
        good_first_issues=triage_issues(issues, now=now),
        avg_pr_merge_days=average_merge_days(pulls),
    )


def _merge_issue_sets(issue_sets: Iterable[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Union per-label issue lists, keeping the first record for each number.

    An issue commonly carries several triage labels, so the same record arrives
    once per matching query.
    """
    merged: dict[int, dict[str, Any]] = {}
    for issues in issue_sets:
        for issue in issues:
            number = issue.get("number")
            if number is not None:
                merged.setdefault(number, issue)
    return list(merged.values())


def _parse_timestamp(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _label_name(label: Any) -> str:
    if isinstance(label, dict):
        return label.get("name", "")
    return str(label)
