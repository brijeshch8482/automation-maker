"""JobService: the custom-automation lifecycle (ARCHITECTURE.md §3, docs/ROUTINES.md §4).

Every routine fire is recorded as a JobAttempt and committed BEFORE the request goes out, so a
crash mid-fire leaves a trace. A fire that may have created a session is never repeated.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import Settings
from api.db import AttemptStatus, Job, JobAttempt, utcnow
from api.dispatch import DispatchError, WorkflowDispatcher
from api.ids import new_job_id
from api.pii import mask_pii
from api.providers import (
    FireRejected,
    FireUnknown,
    GenerationProvider,
    JobContext,
    RetryLater,
)
from api.security import callback_token
from api.states import TERMINAL, JobState, check_transition
from spec.validate import Issue, validate_spec


class JobNotFound(Exception):
    pass


class JobConflict(Exception):
    """The request doesn't fit the job's current state."""


class SpecInvalid(Exception):
    def __init__(self, issues: list[Issue]) -> None:
        super().__init__("; ".join(map(str, issues)))
        self.issues = issues


@dataclass(frozen=True)
class CallbackResult:
    accepted: bool  # False: a duplicate for an attempt that is already closed (ignored)


# Which mode a job in each waiting state fires, used when retrying a rate-limited fire.
_MODE_FOR_STATE = {
    JobState.SPEC_REQUESTED: "spec",
    JobState.QUEUED: "build",
    JobState.REPAIRING: "repair",
}


class JobService:
    def __init__(
        self,
        settings: Settings,
        provider: GenerationProvider,
        dispatcher: WorkflowDispatcher,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self.settings = settings
        self.provider = provider
        self.dispatcher = dispatcher
        self.clock = clock

    # --- Queries ------------------------------------------------------------------------

    async def get_for_user(self, session: AsyncSession, job_id: str, user_id: str) -> Job:
        job = await session.get(Job, job_id)
        if job is None or job.user_id != user_id:
            raise JobNotFound(job_id)
        return job

    async def list_for_user(self, session: AsyncSession, user_id: str) -> list[Job]:
        result = await session.scalars(
            select(Job).where(Job.user_id == user_id).order_by(Job.created_at.desc())
        )
        return list(result)

    # --- User actions -------------------------------------------------------------------

    async def create(self, session: AsyncSession, user_id: str, description: str) -> Job:
        now = self.clock()
        job = Job(
            id=new_job_id(),
            user_id=user_id,
            state=JobState.DRAFT,
            state_changed_at=now,
            # The browser masks too; this is the guard that can't be skipped.
            description=mask_pii(description.strip()),
            assumptions=[],
            questions=[],
            answers=[],
            created_at=now,
            updated_at=now,
        )
        session.add(job)
        self._set_state(job, JobState.SPEC_REQUESTED)
        await self._fire(session, job, "spec")
        return job

    async def answer(self, session: AsyncSession, job: Job, answers: list[dict[str, str]]) -> Job:
        self._require(job, JobState.SPEC_READY)
        masked = [{"question": a["question"], "answer": mask_pii(a["answer"])} for a in answers]
        job.answers = masked  # this round's answers; earlier rounds live in the spec revision
        job.revision += 1
        self._set_state(job, JobState.SPEC_REQUESTED)
        await self._fire(session, job, "spec")
        return job

    async def save_spec(self, session: AsyncSession, job: Job, spec: dict[str, Any]) -> Job:
        self._require(job, JobState.SPEC_READY)
        parsed, issues = validate_spec(spec)
        if parsed is None or issues:
            raise SpecInvalid(issues)
        job.spec = spec
        await session.commit()
        return job

    async def confirm(self, session: AsyncSession, job: Job) -> Job:
        self._require(job, JobState.SPEC_READY)
        if job.spec is None:
            raise JobConflict("the job has no spec to build")
        job.attempt = 0
        self._set_state(job, JobState.QUEUED)
        await self._fire(session, job, "build")
        return job

    # --- Callbacks ----------------------------------------------------------------------

    async def on_routine_callback(
        self, session: AsyncSession, payload: dict[str, Any]
    ) -> CallbackResult:
        """Handle a routine's result. The caller has already checked the job's token."""
        job = await session.get(Job, payload["job_id"])
        if job is None:
            raise JobNotFound(payload["job_id"])

        mode = payload["mode"]
        number = payload.get("revision", 0) if mode == "spec" else payload.get("attempt", 0)
        attempt = _find_attempt(job, mode, number)

        if attempt is not None and attempt.status not in AttemptStatus.AWAITING:
            return CallbackResult(accepted=False)
        if job.state in TERMINAL:
            raise JobConflict(f"job is {job.state}")
        if attempt is None or attempt is not _latest_attempt(job):
            raise JobConflict(f"no open {mode} attempt {number} for this job")

        if mode == "spec":
            await self._on_spec_result(job, attempt, payload)
        else:
            await self._on_generation_result(job, attempt, payload)
        await session.commit()
        return CallbackResult(accepted=True)

    async def on_build_callback(
        self, session: AsyncSession, payload: dict[str, Any]
    ) -> CallbackResult:
        """Handle the Windows build result. The caller has already checked the signature."""
        job = await session.get(Job, payload["job_id"])
        if job is None:
            raise JobNotFound(payload["job_id"])

        attempt = payload["attempt"]
        if attempt < job.attempt or (attempt == job.attempt and job.state != JobState.BUILDING):
            return CallbackResult(accepted=False)  # duplicate for a build already handled
        if job.state != JobState.BUILDING or attempt != job.attempt:
            raise JobConflict(f"job is {job.state} at attempt {job.attempt}")

        job.run_url = payload.get("run_url")
        if payload["status"] == "passed":
            job.artifact_key = payload.get("artifact_key")
            job.guide_key = payload.get("guide_key")
            self._set_state(job, JobState.READY)
        else:
            job.last_report = payload.get("report") or {}
            if job.attempt < self.settings.max_repairs:
                job.attempt += 1
                self._set_state(job, JobState.REPAIRING)
                await self._fire(session, job, "repair")
                return CallbackResult(accepted=True)
            self._fail(job, "the Windows build failed after all repair attempts")
        await session.commit()
        return CallbackResult(accepted=True)

    async def _on_spec_result(self, job: Job, attempt: JobAttempt, payload: dict[str, Any]) -> None:
        now = self.clock()
        attempt.closed_at = now
        if payload["status"] != "ok":
            attempt.status = AttemptStatus.FAILED
            attempt.detail = payload.get("reason")
            self._fail(
                job, f"couldn't design the automation: {payload.get('reason') or 'no reason'}"
            )
            return

        spec = payload.get("spec")
        parsed, issues = validate_spec(spec)
        if parsed is None or issues:
            attempt.status = AttemptStatus.FAILED
            attempt.detail = "; ".join(map(str, issues))[:2000]
            self._fail(job, "the designed spec did not pass validation")
            return

        attempt.status = AttemptStatus.OK
        job.spec = spec
        job.assumptions = list(payload.get("assumptions") or [])
        job.questions = list(payload.get("questions") or [])[:5]
        self._set_state(job, JobState.SPEC_READY)

    async def _on_generation_result(
        self, job: Job, attempt: JobAttempt, payload: dict[str, Any]
    ) -> None:
        attempt.closed_at = self.clock()
        if payload["status"] != "ok":
            # Code generation failures are not repaired: the user can edit the spec and retry.
            attempt.status = AttemptStatus.FAILED
            attempt.detail = "\n".join(
                filter(None, [payload.get("reason"), payload.get("log_tail")])
            )[-8000:]
            self._fail(
                job, f"couldn't generate the automation: {payload.get('reason') or 'no reason'}"
            )
            return

        attempt.status = AttemptStatus.OK
        job.branch = payload["branch"]
        job.commit_sha = payload.get("commit_sha")
        job.used_custom_step = payload.get("used_custom_step")
        try:
            await self.dispatcher.dispatch(job.id, job.branch, job.attempt)
        except DispatchError as err:
            self._fail(job, f"couldn't start the Windows build: {err}")
            return
        self._set_state(job, JobState.BUILDING)

    # --- Background work ----------------------------------------------------------------

    async def retry_pending(self, session: AsyncSession) -> int:
        """Re-fire jobs whose last fire was rate limited and whose retry time has come."""
        now = self.clock()
        jobs = await session.scalars(
            select(Job).where(Job.retry_at.is_not(None), Job.retry_at <= now)
        )
        count = 0
        for job in list(jobs):
            mode = _MODE_FOR_STATE.get(job.state)
            if mode is None or _awaiting_attempt(job) is not None:
                job.retry_at = None
                continue
            await self._fire(session, job, mode)
            count += 1
        await session.commit()
        return count

    async def run_watchdog(self, session: AsyncSession) -> int:
        """Fail jobs that got no callback in time; expire and clean up old data."""
        now = self.clock()
        s = self.settings
        changed = 0
        timeouts = {
            JobState.SPEC_REQUESTED: timedelta(minutes=s.spec_timeout_min),
            JobState.GENERATING: timedelta(minutes=s.generation_timeout_min),
            JobState.REPAIRING: timedelta(minutes=s.generation_timeout_min),
        }
        waiting = await session.scalars(select(Job).where(Job.state.in_(list(timeouts))))
        for job in list(waiting):
            attempt = _awaiting_attempt(job)
            if attempt is not None and now - attempt.created_at > timeouts[job.state]:
                attempt.status = AttemptStatus.TIMED_OUT
                attempt.closed_at = now
                minutes = int(timeouts[job.state].total_seconds() // 60)
                self._fail(job, f"no result from the {attempt.mode} run within {minutes} minutes")
                changed += 1

        building = await session.scalars(
            select(Job).where(
                Job.state == JobState.BUILDING,
                Job.state_changed_at < now - timedelta(minutes=s.build_timeout_min),
            )
        )
        for job in list(building):
            self._fail(
                job, f"no result from the Windows build within {s.build_timeout_min} minutes"
            )
            changed += 1

        stale = await session.scalars(
            select(Job).where(
                Job.state == JobState.SPEC_READY,
                Job.state_changed_at < now - timedelta(days=s.unconfirmed_expiry_days),
            )
        )
        for job in list(stale):
            self._set_state(job, JobState.EXPIRED)
            changed += 1

        old = await session.scalars(
            select(Job).where(
                Job.description.is_not(None),
                Job.created_at < now - timedelta(days=s.description_retention_days),
            )
        )
        for job in list(old):
            job.description = None
            changed += 1

        await session.commit()
        return changed

    # --- Internals ----------------------------------------------------------------------

    async def _fire(self, session: AsyncSession, job: Job, mode: str) -> None:
        now = self.clock()
        attempt = JobAttempt(
            job_id=job.id,
            mode=mode,
            revision=job.revision,
            attempt=job.attempt,
            status=AttemptStatus.FIRING,
            created_at=now,
        )
        job.attempts.append(attempt)
        job.retry_at = None
        await session.commit()  # recorded before the request goes out

        ctx = JobContext(
            job_id=job.id,
            revision=job.revision,
            attempt=job.attempt,
            callback_url=f"{self.settings.public_base_url.rstrip('/')}/internal/routine-callback",
            callback_token=callback_token(
                self.settings.callback_token_secret.get_secret_value(), job.id
            ),
            branch=job.branch,
        )
        try:
            if mode == "spec":
                previous = job.spec if job.revision else None
                answers = job.answers if job.revision else []
                ref = await self.provider.request_spec(
                    ctx, job.description or "", answers, previous
                )
            elif mode == "build":
                ref = await self.provider.request_build(ctx, job.spec or {})
            else:
                ref = await self.provider.request_repair(ctx, job.last_report or {})
        except RetryLater as err:
            attempt.status = AttemptStatus.RATE_LIMITED
            attempt.detail = str(err)
            attempt.closed_at = self.clock()
            job.retry_at = self.clock() + timedelta(seconds=err.retry_after_s)
        except FireUnknown as err:
            # Left awaiting: a late callback is still accepted, else the watchdog fails it.
            attempt.status = AttemptStatus.UNKNOWN
            attempt.detail = str(err)
        except FireRejected as err:
            attempt.status = AttemptStatus.FAILED
            attempt.detail = str(err)
            attempt.closed_at = self.clock()
            self._fail(job, f"couldn't start the {mode} run: {err}")
        else:
            attempt.status = AttemptStatus.OPEN
            attempt.session_id = ref.session_id
            attempt.session_url = ref.session_url
            if mode == "build":
                self._set_state(job, JobState.GENERATING)
        await session.commit()

    def _set_state(self, job: Job, target: JobState) -> None:
        check_transition(JobState(job.state), target)
        job.state = target
        job.state_changed_at = self.clock()

    def _fail(self, job: Job, reason: str) -> None:
        self._set_state(job, JobState.FAILED)
        job.failure_reason = reason
        job.retry_at = None

    @staticmethod
    def _require(job: Job, state: JobState) -> None:
        if job.state != state:
            raise JobConflict(f"job is {job.state}, expected {state}")


def _find_attempt(job: Job, mode: str, number: int) -> JobAttempt | None:
    for attempt in reversed(job.attempts):
        if attempt.mode != mode or attempt.status == AttemptStatus.RATE_LIMITED:
            continue
        if (attempt.revision if mode == "spec" else attempt.attempt) == number:
            return attempt
    return None


def _latest_attempt(job: Job) -> JobAttempt | None:
    real = [a for a in job.attempts if a.status != AttemptStatus.RATE_LIMITED]
    return real[-1] if real else None


def _awaiting_attempt(job: Job) -> JobAttempt | None:
    latest = _latest_attempt(job)
    return latest if latest is not None and latest.status in AttemptStatus.AWAITING else None
