"""Minimal GitHub REST client for the investigator node.

Deliberately not the GitHub MCP Server. MCP exists so an LLM can choose tools at
runtime; this node performs a fixed sequence of deterministic fetches and does
the summarizing itself, so the token saving is identical while the code stays
directly testable. See `specs/agents/github-repo-investigator.md`.

Only the endpoints the investigator needs are implemented. Nothing here returns
raw payloads to callers beyond what the node immediately reduces.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from .errors import RateLimited, RepositoryUnavailable

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
        response = await self._client.get(path, params=params or None)

        if response.status_code in (403, 429) and _is_rate_limited(response):
            raise RateLimited(_reset_epoch(response))
        if response.status_code in (403, 404):
            # GitHub returns 404 rather than 403 for private repos an
            # unauthorized token cannot see, so both map to the same cause.
            raise RepositoryUnavailable(owner, repo)
        response.raise_for_status()
        return response.json()

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

    async def list_merged_pulls(
        self, owner: str, repo: str, per_page: int = 50
    ) -> list[dict[str, Any]]:
        """Return recently closed pull requests, newest first."""
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
