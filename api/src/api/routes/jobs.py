from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from api.auth import CurrentUser
from api.db import Job
from api.downloads import TOKEN_TTL_S, bundle_link
from api.jobs import JobConflict, JobNotFound, SpecInvalid
from api.routes.deps import Jobs, Session, StorageDep
from api.schemas import (
    AnswersIn,
    CreateJob,
    DownloadOut,
    JobCreated,
    JobOut,
    JobSummary,
    SpecIn,
)
from api.states import JobState

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


@router.get("/jobs/{job_id}/bundle")
async def job_bundle(
    job_id: str,
    request: Request,
    user: CurrentUser,
    jobs: Jobs,
    session: Session,
    storage: StorageDep,
) -> DownloadOut:
    """Add to MakeMyEXE for a ready custom app: its signed pack as a .mmx, through the Worker.
    Only the job's owner gets a link (licenses for custom apps come in phase 2e)."""
    job = await _load(jobs, session, job_id, user)
    settings = request.app.state.settings
    secret = settings.download_token_secret.get_secret_value()
    worker = settings.download_worker_url
    if not (job.state == JobState.READY and job.pack and storage and worker and secret):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "no bundle for this app yet")
    guide = (
        storage.link(job.guide_key, filename="Guide.pdf", inline=True).url if job.guide_key else ""
    )
    spec = job.spec or {}
    return DownloadOut(
        version=str(spec.get("version", "")),
        filename=f"{job.pack['exe']}.mmx",
        size_bytes=job.pack.get("bundle_bytes"),
        url=bundle_link(worker, secret, job.pack),
        guide_url=guide,
        expires_in=TOKEN_TTL_S,
    )


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
