"""FastAPI app factory.

uv run uvicorn api.app:create_app --factory --reload
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.auth import TokenVerifier
from api.catalog import Catalog
from api.config import Settings, get_settings
from api.db import Database
from api.dispatch import FakeDispatcher, GitHubDispatcher, WorkflowDispatcher
from api.jobs import JobService
from api.providers import GenerationProvider
from api.providers.fake import FakeProvider
from api.providers.routine import RoutineProvider
from api.routes import catalog, internal, jobs
from api.storage import Storage, make_storage

log = logging.getLogger(__name__)


DEV_SECRET = "dev-only-change-me"


def check_production_settings(settings: Settings) -> None:
    """Refuse to start a deployment, or real routines, on dev defaults.

    Dev secrets would let anyone forge callbacks; dev auth would let anyone sign in as anyone;
    SQLite inside a Render container is wiped on every deploy.
    """
    deployed = settings.on_render or not settings.uses_sqlite
    if settings.provider != "routine" and not deployed:
        return
    problems = [
        name.upper()
        for name in ("callback_token_secret", "build_callback_secret")
        if getattr(settings, name).get_secret_value() in ("", DEV_SECRET)
    ]
    if settings.dev_auth:
        problems.append("DEV_AUTH must be false")
    if settings.on_render and settings.uses_sqlite:
        problems.append("DATABASE_URL must point to Postgres")
    if problems:
        raise RuntimeError(f"unsafe settings for a deployment: {', '.join(problems)}")


def make_provider(settings: Settings) -> GenerationProvider:
    if settings.provider == "routine":
        return RoutineProvider(
            spec_url=settings.routine_spec_url,
            spec_token=settings.routine_spec_token.get_secret_value(),
            build_url=settings.routine_build_url,
            build_token=settings.routine_build_token.get_secret_value(),
        )
    if settings.provider == "fake":
        return FakeProvider()
    raise ValueError(f"unknown provider {settings.provider!r}")


def make_dispatcher(settings: Settings) -> WorkflowDispatcher:
    token = settings.builds_github_token.get_secret_value()
    if not token:
        return FakeDispatcher()
    return GitHubDispatcher(
        token=token, repo=settings.builds_repo, workflow=settings.builds_workflow
    )


async def _background_loop(app: FastAPI, interval_s: int) -> None:
    service: JobService = app.state.jobs
    while True:
        await asyncio.sleep(interval_s)
        try:
            async with app.state.db.sessions() as session:
                await service.retry_pending(session)
            async with app.state.db.sessions() as session:
                await service.run_watchdog(session)
        except Exception:
            log.exception("background job loop failed")


def create_app(
    settings: Settings | None = None,
    provider: GenerationProvider | None = None,
    dispatcher: WorkflowDispatcher | None = None,
    storage: Storage | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    check_production_settings(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if settings.uses_sqlite:
            await app.state.db.create_all()  # Postgres is migrated by `python -m api.migrate`
        task = None
        if settings.watchdog_interval_s > 0:
            task = asyncio.create_task(_background_loop(app, settings.watchdog_interval_s))
        yield
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await app.state.db.dispose()

    app = FastAPI(title="MakeMyEXE API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.db = Database(settings.database_url)
    app.state.catalog = Catalog.load(settings.catalog_dir)
    app.state.storage = storage if storage is not None else make_storage(settings)
    app.state.auth = TokenVerifier(settings)
    app.state.jobs = JobService(
        settings, provider or make_provider(settings), dispatcher or make_dispatcher(settings)
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.include_router(catalog.router)
    app.include_router(jobs.router)
    app.include_router(internal.router)

    @app.get("/health", include_in_schema=False)
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
