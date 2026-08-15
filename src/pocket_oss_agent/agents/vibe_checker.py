"""repo-vibe-checker: score contributor-friendliness for a repository.

Implements `specs/agents/repo-vibe-checker.md`. Consumes `repo_facts` from
`github-repo-investigator` and produces `vibe_summary`.

Every threshold lives in a named constant so tuning them does not mean editing
prose or hunting through branches.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from ..github_client import GitHubClient
from ..state import RepoFacts, VibeSummary

# Step 1: days since the most recent commit.
COMMIT_ACTIVE_DAYS = 7
COMMIT_MODERATE_DAYS = 30
COMMIT_SLOWING_DAYS = 90

# Step 2: average days to the first maintainer reply.
RESPONSE_FAST_DAYS = 2
RESPONSE_MODERATE_DAYS = 7
MAX_ISSUES_SAMPLED = 20

# Step 3: merged share of closed pull requests.
PR_WINDOW_DAYS = 90
HEALTHY_MERGE_RATE = 0.60
REJECTION_RISK_MERGE_RATE = 0.70

# Step 4: welcome signals.
WELCOMING_SCORE = 4
MODERATE_SCORE = 2

#: `author_association` values that imply write access to the repository.
MAINTAINER_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})

COMMIT_STATUS_LABELS = {
    "actively_maintained": "🟢 Actively maintained",
    "moderate_activity": "🟡 Moderate activity",
    "slowing_down": "🟠 Slowing down",
    "potentially_dormant": "🔴 Potentially dormant",
}


def commit_recency(commits: list[dict[str, Any]], *, now: datetime | None = None):
    """Return ``(days_since_last_commit, status)``.

    Returns ``(None, None)`` for a repository with no commits, which the caller
    reports as an unresolved signal rather than as dormancy.
    """
    now = now or datetime.now(UTC)
    timestamps = [ts for ts in (_commit_timestamp(commit) for commit in commits) if ts is not None]
    if not timestamps:
        return None, None

    days = max((now - max(timestamps)).days, 0)
    if days <= COMMIT_ACTIVE_DAYS:
        return days, "actively_maintained"
    if days <= COMMIT_MODERATE_DAYS:
        return days, "moderate_activity"
    if days <= COMMIT_SLOWING_DAYS:
        return days, "slowing_down"
    return days, "potentially_dormant"


def response_status(avg_days: float | None) -> str | None:
    """Bucket an average first-response time."""
    if avg_days is None:
        return None
    if avg_days < RESPONSE_FAST_DAYS:
        return "very_responsive"
    if avg_days <= RESPONSE_MODERATE_DAYS:
        return "moderate"
    return "slow_to_respond"


def first_maintainer_reply_days(issue: dict[str, Any], comments: list[dict[str, Any]]):
    """Days from an issue opening to its first reply from someone with write access.

    Contributors answering each other is not maintainer responsiveness, so
    comments from `CONTRIBUTOR` or `NONE` are ignored. Returns None when the
    issue never drew a maintainer reply, which excludes it from the average
    rather than counting as an instant response.
    """
    created = _parse_timestamp(issue.get("created_at"))
    if created is None:
        return None

    replies = [
        ts
        for comment in comments
        if comment.get("author_association") in MAINTAINER_ASSOCIATIONS
        and (ts := _parse_timestamp(comment.get("created_at"))) is not None
        and ts >= created
    ]
    if not replies:
        return None
    return (min(replies) - created).total_seconds() / 86400


def merge_rate_from_counts(merged: int, closed: int) -> float | None:
    """Merged share of closed pull requests.

    Returns None when nothing closed in the window, which is reported as an
    unresolved signal rather than as a 0% merge rate.
    """
    if closed <= 0:
        return None
    return round(merged / closed, 2)


def merge_rate_queries(owner: str, repo: str, *, now: datetime | None = None) -> tuple[str, str]:
    """Build the ``(merged, closed)`` search queries for the activity window."""
    now = now or datetime.now(UTC)
    since = (now - timedelta(days=PR_WINDOW_DAYS)).date().isoformat()
    base = f"repo:{owner}/{repo} is:pr closed:>={since}"
    return f"{base} is:merged", f"{base} is:closed"


def is_high_rejection_risk(merge_rate: float | None) -> bool:
    """Whether over 30 percent of closed PRs were closed without merging."""
    return merge_rate is not None and merge_rate < REJECTION_RISK_MERGE_RATE


def is_healthy_merge_rate(merge_rate: float | None) -> bool:
    return merge_rate is not None and merge_rate > HEALTHY_MERGE_RATE


def welcome_signals(profile: dict[str, Any] | None, *, has_good_first_issues: bool):
    """Return ``(score, rating)`` over the four newcomer signals.

    Three come from the community profile; the fourth reuses the triage results
    already in `repo_facts` rather than re-querying labels.
    """
    files = (profile or {}).get("files") or {}
    score = sum(
        [
            files.get("contributing") is not None,
            files.get("code_of_conduct") is not None,
            files.get("issue_template") is not None,
            has_good_first_issues,
        ]
    )

    if score >= WELCOMING_SCORE:
        rating = "welcoming"
    elif score >= MODERATE_SCORE:
        rating = "moderate"
    else:
        rating = "unfriendly"
    return score, rating


def compose_summary(
    *,
    commit_days: int | None,
    commit_status: str | None,
    avg_response_days: float | None,
    merge_rate: float | None,
    welcome_score: int,
    welcome_rating: str,
    good_first_issue_count: int,
) -> str:
    """Build the two to three sentence summary shown in the roadmap."""
    parts: list[str] = []

    if commit_status:
        label = COMMIT_STATUS_LABELS[commit_status].split(" ", 1)[1].lower()
        parts.append(f"This repo is {label} (last commit {commit_days} days ago)")
    else:
        parts.append("Commit activity could not be determined")

    if avg_response_days is not None:
        parts.append(f"maintainers reply to issues in about {avg_response_days:.1f} days")
    else:
        parts.append("no recent maintainer replies were found to measure response time")

    second: list[str] = []
    if good_first_issue_count:
        second.append(f"There are {good_first_issue_count} open beginner-friendly issues")
    if merge_rate is not None:
        # No .capitalize() here: it lowercases the rest of the string, turning
        # "PRs" into "prs". The clause already starts with a digit.
        second.append(f"{merge_rate:.0%} of recently closed PRs were merged")

    sentences = [f"{' and '.join(parts)}."]
    if second:
        sentences.append(f"{', and '.join(second)}.")
    sentences.append(f"Overall vibe: {welcome_rating} ({welcome_score}/4 welcome signals).")
    return " ".join(sentences)


async def check_vibe(
    repo_facts: RepoFacts, client: GitHubClient, *, now: datetime | None = None
) -> VibeSummary:
    """Run the vibe check and return the sentiment report.

    Propagates `RepositoryUnavailable` and `RateLimited` from the client. A
    partial score is never reported as complete.
    """
    owner, repo = repo_facts.owner, repo_facts.repo
    merged_query, closed_query = merge_rate_queries(owner, repo, now=now)

    commits, issues, merged, closed, profile = await asyncio.gather(
        client.list_commits(owner, repo),
        client.list_recent_issues(owner, repo),
        client.count_matching_issues(merged_query),
        client.count_matching_issues(closed_query),
        client.get_community_profile(owner, repo),
    )

    commit_days, commit_status = commit_recency(commits, now=now)
    avg_response_days = await _average_response_days(owner, repo, issues, client)
    merge_rate = merge_rate_from_counts(merged, closed)
    score, rating = welcome_signals(
        profile, has_good_first_issues=bool(repo_facts.good_first_issues)
    )

    return VibeSummary(
        commit_recency_days=commit_days if commit_days is not None else -1,
        commit_status=commit_status or "unknown",
        avg_issue_response_days=avg_response_days,
        response_status=response_status(avg_response_days),
        pr_merge_rate=merge_rate,
        welcome_score=score,
        welcome_rating=rating,
        vibe_summary=compose_summary(
            commit_days=commit_days,
            commit_status=commit_status,
            avg_response_days=avg_response_days,
            merge_rate=merge_rate,
            welcome_score=score,
            welcome_rating=rating,
            good_first_issue_count=len(repo_facts.good_first_issues),
        ),
    )


async def _average_response_days(
    owner: str, repo: str, issues: list[dict[str, Any]], client: GitHubClient
) -> float | None:
    """Average first-maintainer-reply time over recently commented issues.

    Comments are not included in the issues listing, so each sampled issue costs
    one request. The sample is capped and the requests are issued concurrently.
    """
    sampled = [
        issue
        for issue in issues
        if issue.get("pull_request") is None and (issue.get("comments") or 0) > 0
    ][:MAX_ISSUES_SAMPLED]
    if not sampled:
        return None

    comment_sets = await asyncio.gather(
        *(client.list_issue_comments(owner, repo, issue["number"]) for issue in sampled)
    )

    durations = [
        days
        for issue, comments in zip(sampled, comment_sets, strict=True)
        if (days := first_maintainer_reply_days(issue, comments)) is not None
    ]
    if not durations:
        return None
    return round(sum(durations) / len(durations), 2)


def _commit_timestamp(commit: dict[str, Any]) -> datetime | None:
    committer = (commit.get("commit") or {}).get("committer") or {}
    return _parse_timestamp(committer.get("date"))


def _parse_timestamp(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
