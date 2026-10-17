from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from api.auth import CurrentUser
from api.db import Job
from api.jobs import JobConflict, JobNotFound, SpecInvalid
from api.routes.deps import Jobs, Session, StorageDep
from api.schemas import AnswersIn, CreateJob, JobCreated, JobOut, JobSummary, SpecIn

router = APIRouter(tags=["jobs"])


async def _load(jobs: Jobs, session: Session, job_id: str, user: str) -> Job:
    try:
        return await jobs.get_for_user(session, job_id, user)
    except JobNotFound as err:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found") from err


def _conflict(err: JobConflict) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, str(err))


@router.post("/jobs", status_code=status.HTTP_202_ACCEPTED)
async def create_job(
    body: CreateJob, user: CurrentUser, jobs: Jobs, session: Session
) -> JobCreated:
    job = await jobs.create(session, user, body.description)
    return JobCreated(job_id=job.id)


@router.get("/jobs/{job_id}")
async def get_job(
    job_id: str, user: CurrentUser, jobs: Jobs, session: Session, storage: StorageDep
) -> JobOut:
    return JobOut.of(await _load(jobs, session, job_id, user), storage)


@router.post("/jobs/{job_id}/answers", status_code=status.HTTP_202_ACCEPTED)
async def answer_questions(
    job_id: str, body: AnswersIn, user: CurrentUser, jobs: Jobs, session: Session
) -> JobOut:
    job = await _load(jobs, session, job_id, user)
    try:
        await jobs.answer(session, job, [a.model_dump() for a in body.answers])
    except JobConflict as err:
        raise _conflict(err) from err
    return JobOut.of(job)


@router.put("/jobs/{job_id}/spec")
async def save_spec(
    job_id: str, body: SpecIn, user: CurrentUser, jobs: Jobs, session: Session
) -> JobOut:
    job = await _load(jobs, session, job_id, user)
    try:
        await jobs.save_spec(session, job, body.spec)
    except JobConflict as err:
        raise _conflict(err) from err
    except SpecInvalid as err:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"message": "spec is not valid", "issues": [str(i) for i in err.issues]},
        ) from err
    return JobOut.of(job)


@router.post("/jobs/{job_id}/confirm", status_code=status.HTTP_202_ACCEPTED)
async def confirm_spec(job_id: str, user: CurrentUser, jobs: Jobs, session: Session) -> JobOut:
    job = await _load(jobs, session, job_id, user)
    try:
        await jobs.confirm(session, job)
    except JobConflict as err:
        raise _conflict(err) from err
    return JobOut.of(job)


@router.get("/me/jobs")
async def my_jobs(user: CurrentUser, jobs: Jobs, session: Session) -> list[JobSummary]:
    return [JobSummary.of(job) for job in await jobs.list_for_user(session, user)]
