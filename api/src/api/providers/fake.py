"""FakeProvider: records fires instead of calling a routine. For tests and local dev.

Locally, play the routine yourself by POSTing to /internal/routine-callback (see CLAUDE.md).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from api.providers.base import JobContext, RunRef


@dataclass
class FakeProvider:
    calls: list[tuple[str, JobContext, dict[str, Any]]] = field(default_factory=list)
    # Exceptions to raise on the next fires, in order (e.g. RetryLater, FireUnknown).
    fail_next: list[Exception] = field(default_factory=list)

    def _record(self, mode: str, job: JobContext, data: dict[str, Any]) -> RunRef:
        if self.fail_next:
            raise self.fail_next.pop(0)
        self.calls.append((mode, job, data))
        n = len(self.calls)
        return RunRef(f"session_fake_{n}", f"https://claude.ai/code/session_fake_{n}")

    async def request_spec(
        self,
        job: JobContext,
        description: str,
        answers: list[dict[str, str]],
        previous_spec: dict[str, Any] | None,
    ) -> RunRef:
        data = {"description": description, "answers": answers, "previous_spec": previous_spec}
        return self._record("spec", job, data)

    async def request_build(self, job: JobContext, spec: dict[str, Any]) -> RunRef:
        return self._record("build", job, {"spec": spec})

    async def request_repair(self, job: JobContext, report: dict[str, Any]) -> RunRef:
        return self._record("repair", job, {"report": report})
