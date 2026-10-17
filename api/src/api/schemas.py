"""Request and response bodies."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from api.db import Job
from api.states import JobState
from api.storage import Storage


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- Catalog ----------------------------------------------------------------------------


class AutomationSummary(BaseModel):
    id: str
    title: str
    description: str = ""
    category: str
    version: str
    network: dict[str, Any]

    @classmethod
    def of(cls, spec: dict[str, Any]) -> AutomationSummary:
        return cls(
            id=spec["id"],
            title=spec["title"],
            description=spec.get("description", ""),
            category=spec["category"],
            version=spec["version"],
            network=spec.get("network") or {"required": False, "domains": []},
        )


class DownloadOut(BaseModel):
    version: str
    filename: str
    size_bytes: int | None
    url: str
    guide_url: str
    expires_in: int
    built_at: str | None = None


# --- Jobs -------------------------------------------------------------------------------


class CreateJob(_In):
    description: str = Field(min_length=10, max_length=4000)


class JobCreated(BaseModel):
    job_id: str


class Answer(_In):
    question: str = Field(min_length=1, max_length=500)
    answer: str = Field(min_length=1, max_length=2000)


class AnswersIn(_In):
    answers: list[Answer] = Field(min_length=1, max_length=5)


class SpecIn(_In):
    spec: dict[str, Any]


class AttemptOut(BaseModel):
    mode: str
    revision: int
    attempt: int
    status: str
    session_url: str | None
    created_at: datetime


class JobOut(BaseModel):
    id: str
    state: str
    description: str | None
    spec: dict[str, Any] | None
    assumptions: list[str]
    questions: list[str]
    revision: int
    attempt: int
    failure_reason: str | None
    run_url: str | None
    # Short-lived links to the finished app, only when the job is ready and R2 is configured.
    download_url: str | None = None
    guide_url: str | None = None
    created_at: datetime
    updated_at: datetime
    attempts: list[AttemptOut]

    @classmethod
    def of(cls, job: Job, storage: Storage | None = None) -> JobOut:
        download_url = guide_url = None
        if storage and job.state == JobState.READY and job.artifact_key:
            filename = job.artifact_key.rsplit("/", 1)[-1]
            download_url = storage.link(job.artifact_key, filename=filename).url
            if job.guide_key:
                guide_url = storage.link(job.guide_key, filename="Guide.pdf", inline=True).url
        return cls(
            download_url=download_url,
            guide_url=guide_url,
            id=job.id,
            state=job.state,
            description=job.description,
            spec=job.spec,
            assumptions=job.assumptions,
            questions=job.questions,
            revision=job.revision,
            attempt=job.attempt,
            failure_reason=job.failure_reason,
            run_url=job.run_url,
            created_at=job.created_at,
            updated_at=job.updated_at,
            attempts=[
                AttemptOut(
                    mode=a.mode,
                    revision=a.revision,
                    attempt=a.attempt,
                    status=a.status,
                    session_url=a.session_url,
                    created_at=a.created_at,
                )
                for a in job.attempts
            ],
        )


class JobSummary(BaseModel):
    id: str
    state: str
    title: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, job: Job) -> JobSummary:
        title = job.spec.get("title") if job.spec else None
        return cls(
            id=job.id,
            state=job.state,
            title=title,
            created_at=job.created_at,
            updated_at=job.updated_at,
        )


# --- Callbacks (docs/ROUTINES.md §4) ------------------------------------------------------


class RoutineCallback(BaseModel):
    model_config = ConfigDict(extra="ignore")

    job_id: str
    mode: Literal["spec", "build", "repair"]
    status: Literal["ok", "failed"]
    revision: int = 0
    attempt: int = 0
    reason: str | None = None
    # spec
    spec: dict[str, Any] | None = None
    assumptions: list[str] = Field(default_factory=list, max_length=50)
    questions: list[str] = Field(default_factory=list, max_length=20)
    # build / repair
    branch: str | None = Field(default=None, pattern=r"^claude/job-job_[0-9A-Z]{26}$")
    # The full SHA: the Windows build refuses the branch unless its head is this commit.
    commit_sha: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")
    used_custom_step: bool | None = None
    log_tail: str | None = Field(default=None, max_length=20_000)


class BuildReport(BaseModel):
    model_config = ConfigDict(extra="ignore")

    stage: str | None = None
    command: str | None = None
    test: str | None = None
    log_tail: str | None = Field(default=None, max_length=20_000)


class BuildCallback(BaseModel):
    model_config = ConfigDict(extra="ignore")

    job_id: str
    attempt: int = Field(ge=0)
    status: Literal["passed", "failed"]
    run_url: str | None = None
    artifact_key: str | None = None
    guide_key: str | None = None
    report: BuildReport | None = None
