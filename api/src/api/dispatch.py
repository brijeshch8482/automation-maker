"""Start the Windows build workflow in automation-builds (docs/ROUTINES.md §5)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import httpx


class DispatchError(Exception):
    pass


class WorkflowDispatcher(Protocol):
    async def dispatch(
        self, job_id: str, branch: str, attempt: int, *, commit: str, spec_sha256: str
    ) -> None: ...


class GitHubDispatcher:
    """workflow_dispatch on `main`, so the workflow file always comes from main.

    The build is pinned: Job 1 refuses the job branch unless its head is `commit` (what the
    routine checked) and spec.json has the fingerprint `spec_sha256` (what the user confirmed).
    """

    def __init__(
        self, *, token: str, repo: str, workflow: str, client: httpx.AsyncClient | None = None
    ) -> None:
        self._token = token
        self._url = f"https://api.github.com/repos/{repo}/actions/workflows/{workflow}/dispatches"
        self._client = client or httpx.AsyncClient(timeout=20.0)

    async def dispatch(
        self, job_id: str, branch: str, attempt: int, *, commit: str, spec_sha256: str
    ) -> None:
        if not self._token:
            raise DispatchError("BUILDS_GITHUB_TOKEN is not configured")
        body = {
            "ref": "main",
            "inputs": {
                "job_id": job_id,
                "branch": branch,
                "attempt": str(attempt),
                "commit": commit,
                "spec_sha256": spec_sha256,
            },
        }
        try:
            response = await self._client.post(
                self._url,
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                json=body,
            )
        except httpx.HTTPError as err:
            raise DispatchError(f"could not reach GitHub: {err!r}") from err
        if response.status_code != 204:
            raise DispatchError(f"GitHub returned {response.status_code}: {response.text[:300]}")


@dataclass
class FakeDispatcher:
    calls: list[tuple[str, str, int]] = field(default_factory=list)
    pins: list[tuple[str, str]] = field(default_factory=list)  # (commit, spec_sha256) per call
    fail: bool = False

    async def dispatch(
        self, job_id: str, branch: str, attempt: int, *, commit: str, spec_sha256: str
    ) -> None:
        if self.fail:
            raise DispatchError("dispatch failed (fake)")
        self.calls.append((job_id, branch, attempt))
        self.pins.append((commit, spec_sha256))
