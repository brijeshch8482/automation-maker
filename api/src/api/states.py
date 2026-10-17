"""Job states and allowed transitions (ARCHITECTURE.md §3)."""

from __future__ import annotations

from enum import StrEnum


class JobState(StrEnum):
    DRAFT = "draft"
    SPEC_REQUESTED = "spec_requested"
    SPEC_READY = "spec_ready"
    QUEUED = "queued"
    GENERATING = "generating"
    BUILDING = "building"
    REPAIRING = "repairing"
    READY = "ready"
    FAILED = "failed"
    EXPIRED = "expired"


TERMINAL = frozenset({JobState.READY, JobState.FAILED, JobState.EXPIRED})

TRANSITIONS: dict[JobState, frozenset[JobState]] = {
    JobState.DRAFT: frozenset({JobState.SPEC_REQUESTED, JobState.FAILED}),
    JobState.SPEC_REQUESTED: frozenset({JobState.SPEC_READY, JobState.FAILED}),
    JobState.SPEC_READY: frozenset(
        {JobState.SPEC_REQUESTED, JobState.QUEUED, JobState.EXPIRED, JobState.FAILED}
    ),
    JobState.QUEUED: frozenset({JobState.GENERATING, JobState.FAILED}),
    JobState.GENERATING: frozenset({JobState.BUILDING, JobState.FAILED}),
    JobState.BUILDING: frozenset({JobState.READY, JobState.REPAIRING, JobState.FAILED}),
    JobState.REPAIRING: frozenset({JobState.BUILDING, JobState.FAILED}),
    JobState.READY: frozenset(),
    JobState.FAILED: frozenset(),
    JobState.EXPIRED: frozenset(),
}


class InvalidTransition(Exception):
    def __init__(self, current: JobState, target: JobState) -> None:
        super().__init__(f"cannot move a job from {current} to {target}")
        self.current = current
        self.target = target


def check_transition(current: JobState, target: JobState) -> None:
    if target not in TRANSITIONS[current]:
        raise InvalidTransition(current, target)
