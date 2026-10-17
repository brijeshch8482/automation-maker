"""Database: async SQLAlchemy models for jobs and their attempts.

SQLite (aiosqlite) for local dev and tests, Postgres (asyncpg) in deployment.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, TypeDecorator
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from api.states import JobState


def utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    """Stores UTC; always returns aware datetimes (SQLite drops the tzinfo)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("naive datetime")
        return value.astimezone(UTC) if value is not None else None

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


class Base(DeclarativeBase):
    pass


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    state: Mapped[JobState] = mapped_column(String(20), index=True)
    state_changed_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    # PII-masked description; set to None after the retention period.
    description: Mapped[str | None] = mapped_column(Text)
    spec: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    assumptions: Mapped[list[str]] = mapped_column(JSON, default=list)
    questions: Mapped[list[str]] = mapped_column(JSON, default=list)
    # Answers sent with the latest spec revision.
    answers: Mapped[list[dict[str, str]]] = mapped_column(JSON, default=list)
    revision: Mapped[int] = mapped_column(Integer, default=0)

    # Build: attempt 0 is the first build, 1..max_repairs are repairs.
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    branch: Mapped[str | None] = mapped_column(String(120))
    commit_sha: Mapped[str | None] = mapped_column(String(64))
    used_custom_step: Mapped[bool | None]
    run_url: Mapped[str | None] = mapped_column(Text)
    artifact_key: Mapped[str | None] = mapped_column(Text)
    guide_key: Mapped[str | None] = mapped_column(Text)
    last_report: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    failure_reason: Mapped[str | None] = mapped_column(Text)

    # Set when a fire was rate limited; the background loop retries after this time.
    retry_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    attempts: Mapped[list[JobAttempt]] = relationship(
        back_populates="job", order_by="JobAttempt.id", lazy="selectin"
    )


class AttemptStatus:
    FIRING = "firing"  # row written, fire request in flight
    OPEN = "open"  # routine session running, waiting for its callback
    UNKNOWN = "unknown"  # fire may or may not have created a session; never re-fired
    RATE_LIMITED = "rate_limited"  # 429, nothing created; the job retries later
    OK = "ok"
    FAILED = "failed"
    TIMED_OUT = "timed_out"

    # Attempts that may still receive a callback.
    AWAITING = frozenset({FIRING, OPEN, UNKNOWN})


class JobAttempt(Base):
    """One routine fire. Stores the session link so every job has a trace of what Claude did."""

    __tablename__ = "job_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    mode: Mapped[str] = mapped_column(String(10))  # spec | build | repair
    revision: Mapped[int] = mapped_column(Integer, default=0)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default=AttemptStatus.FIRING)
    session_id: Mapped[str | None] = mapped_column(String(120))
    session_url: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    job: Mapped[Job] = relationship(back_populates="attempts")


class Database:
    def __init__(self, url: str) -> None:
        self.engine: AsyncEngine = create_async_engine(url)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def create_all(self) -> None:
        # Phase 3 dev schema. Alembic migrations come with the first Postgres deployment.
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.sessions() as session:
            yield session

    async def dispose(self) -> None:
        await self.engine.dispose()
