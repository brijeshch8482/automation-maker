from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class RunRef:
    """Where a generation run can be followed (a routine session, later a Managed Agents run)."""

    session_id: str
    session_url: str


@dataclass(frozen=True)
class JobContext:
    """What a provider needs to know about the job it is firing for."""

    job_id: str
    revision: int
    attempt: int
    callback_url: str
    callback_token: str
    branch: str | None = None


class FireError(Exception):
    pass


class RetryLater(FireError):
    """Nothing was created (rate limit, could not connect). Safe to fire again later."""

    def __init__(self, retry_after_s: int, reason: str) -> None:
        super().__init__(reason)
        self.retry_after_s = retry_after_s


class FireUnknown(FireError):
    """The request may have created a run (timeout after sending, 5xx). Never re-fire."""


class FireRejected(FireError):
    """The request was refused and created nothing (4xx other than 429, payload too big)."""


class GenerationProvider(Protocol):
    async def request_spec(
        self,
        job: JobContext,
        description: str,
        answers: list[dict[str, str]],
        previous_spec: dict[str, Any] | None,
    ) -> RunRef: ...

    async def request_build(self, job: JobContext, spec: dict[str, Any]) -> RunRef: ...

    async def request_repair(self, job: JobContext, report: dict[str, Any]) -> RunRef: ...
