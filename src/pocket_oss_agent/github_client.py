"""Minimal GitHub REST client for the investigator node.

Deliberately not the GitHub MCP Server. MCP exists so an LLM can choose tools at
runtime; this node performs a fixed sequence of deterministic fetches and does
the summarizing itself, so the token saving is identical while the code stays
directly testable. See `specs/agents/github-repo-investigator.md`.

Only the endpoints the investigator needs are implemented. Nothing here returns
raw payloads to callers beyond what the node immediately reduces.
"""

from __future__ import annotations

import base64
import os
from typing import Any

import httpx

from .errors import NetworkUnavailable, RateLimited, RepositoryUnavailable

API_ROOT = "https://api.github.com"
_ACCEPT = "application/vnd.github+json"


class GitHubClient:
    """Thin async wrapper over the endpoints the investigator uses."""

    def __init__(self, token: str | None = None, client: httpx.AsyncClient | None = None) -> None:
        self._token = token if token is not None else os.environ.get("GITHUB_TOKEN")
        headers = {"Accept": _ACCEPT}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        self._client = client or httpx.AsyncClient(base_url=API_ROOT, headers=headers, timeout=20.0)
        self._owns_client = client is None

    async def __aenter__(self) -> GitHubClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _get(self, path: str, owner: str, repo: str, **params: Any) -> Any:
        response = await self._request(path, params or None)

        if response.status_code in (403, 429) and _is_rate_limited(response):
            raise RateLimited(_reset_epoch(response))
        if response.status_code in (403, 404):
            # GitHub returns 404 rather than 403 for private repos an
            # unauthorized token cannot see, so both map to the same cause.
            raise RepositoryUnavailable(owner, repo)
        response.raise_for_status()
        return response.json()

    async def _request(self, path: str, params: dict[str, Any] | None) -> httpx.Response:
        """Issue the GET, mapping transport failures onto the pipeline's errors."""
        try:
            return await self._client.get(path, params=params)
        except httpx.HTTPError as exc:
            raise NetworkUnavailable(path, exc) from exc

    async def _get_optional(self, path: str, owner: str, repo: str, **params: Any) -> Any | None:
        """Like `_get`, but returns None for a 404 instead of aborting.

        For endpoints whose absence is information rather than failure. Rate
        limiting still raises, so a throttled request is never mistaken for a
        missing resource.
        """
        try:
            return await self._get(path, owner, repo, **params)
        except RepositoryUnavailable:
            return None

    async def get_tree(self, owner: str, repo: str, ref: str = "HEAD") -> list[dict[str, Any]]:
        """Return the top-level tree entries for a ref.

        Deliberately not recursive. The Architecture Snapshot only reads root
        entries, while a recursive fetch costs the entire file listing:
        rust-lang/rust returns 64,727 entries and is truncated by the API, so
        the extra payload is both wasteful and unreliable.
        """
        payload = await self._get(f"/repos/{owner}/{repo}/git/trees/{ref}", owner, repo)
        return payload.get("tree", [])

    async def list_issues(
        self, owner: str, repo: str, label: str, per_page: int = 100
    ) -> list[dict[str, Any]]:
        """Return open issues carrying ``label``.

        Takes exactly one label. GitHub's ``labels`` parameter is conjunctive:
        passing "good first issue,help wanted" matches only issues carrying both,
        which is almost never any issue. Callers wanting the union must request
        each label separately, so this signature makes that impossible to get
        wrong by accident.
        """
        payload = await self._get(
            f"/repos/{owner}/{repo}/issues",
            owner,
            repo,
            state="open",
            labels=label,
            per_page=per_page,
            sort="updated",
            direction="desc",
        )
        return payload if isinstance(payload, list) else []

    async def list_closed_pulls(
        self, owner: str, repo: str, per_page: int = 50
    ) -> list[dict[str, Any]]:
        """Return recently closed pull requests, newest first.

        Includes those closed without merging. `repo-vibe-checker` needs both
        outcomes to compute a merge rate, and `github-repo-investigator`
        filters to merged ones itself.
        """
        payload = await self._get(
            f"/repos/{owner}/{repo}/pulls",
            owner,
            repo,
            state="closed",
            per_page=per_page,
            sort="updated",
            direction="desc",
        )
        return payload if isinstance(payload, list) else []

    async def list_commits(self, owner: str, repo: str, per_page: int = 10) -> list[dict[str, Any]]:
        """Return the most recent commits on the default branch, newest first."""
        payload = await self._get(f"/repos/{owner}/{repo}/commits", owner, repo, per_page=per_page)
        return payload if isinstance(payload, list) else []

    async def list_recent_issues(
        self, owner: str, repo: str, per_page: int = 50
    ) -> list[dict[str, Any]]:
        """Return recently updated issues regardless of label or state."""
        payload = await self._get(
            f"/repos/{owner}/{repo}/issues",
            owner,
            repo,
            state="all",
            per_page=per_page,
            sort="created",
            direction="desc",
        )
        return payload if isinstance(payload, list) else []

    async def list_issue_comments(
        self, owner: str, repo: str, number: int, per_page: int = 30
    ) -> list[dict[str, Any]]:
        """Return comments on one issue, oldest first."""
        payload = await self._get(
            f"/repos/{owner}/{repo}/issues/{number}/comments", owner, repo, per_page=per_page
        )
        return payload if isinstance(payload, list) else []

    async def get_issue(self, owner: str, repo: str, number: int) -> dict[str, Any] | None:
        """Return one issue's full record, including its body.

        `list_issues` and `list_recent_issues` return bodies too, but callers
        that only need titles and labels use them for a whole page in one
        call; this exists for the one place that actually needs a single
        issue's body - `repo-analyst`, not the listing endpoints.
        """
        payload = await self._get_optional(f"/repos/{owner}/{repo}/issues/{number}", owner, repo)
        return payload if isinstance(payload, dict) else None

    async def get_file_text(
        self, owner: str, repo: str, path: str, max_bytes: int = 64_000
    ) -> str | None:
        """Return a repository file decoded as text, or None if absent.

        Oversized or binary files return None rather than raising: a caller
        parsing a config file wants to skip what it cannot read, not abort.
        """
        payload = await self._get_optional(f"/repos/{owner}/{repo}/contents/{path}", owner, repo)
        if not isinstance(payload, dict) or payload.get("encoding") != "base64":
            return None
        if (payload.get("size") or 0) > max_bytes:
            return None
        try:
            return base64.b64decode(payload.get("content", "")).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return None

    async def count_matching_issues(self, query: str) -> int:
        """Return how many issues or pull requests match a search query.

        Used where an exact total matters more than the records themselves.
        Listing endpoints cannot sort by close date, so paging them gives a
        biased sample: psf/requests had 113 pull requests closed in a 90 day
        window, of which a 50-item page sorted by update time saw only some.
        """
        response = await self._request("/search/issues", {"q": query, "per_page": 1})

        if response.status_code in (403, 429) and _is_rate_limited(response):
            raise RateLimited(_reset_epoch(response))
        response.raise_for_status()
        return response.json().get("total_count", 0)

    async def get_community_profile(self, owner: str, repo: str) -> dict[str, Any] | None:
        """Return the community health profile, or None if unavailable.

        One call reports whether CONTRIBUTING, CODE_OF_CONDUCT and an issue
        template exist, replacing three separate content lookups.
        """
        payload = await self._get_optional(f"/repos/{owner}/{repo}/community/profile", owner, repo)
        return payload if isinstance(payload, dict) else None


def _is_rate_limited(response: httpx.Response) -> bool:
    if response.headers.get("x-ratelimit-remaining") == "0":
        return True
    body = response.text.lower()
    return "rate limit" in body or "secondary rate" in body


def _reset_epoch(response: httpx.Response) -> int | None:
    raw = response.headers.get("x-ratelimit-reset")
    try:
        return int(raw) if raw else None
    except ValueError:
        return None
