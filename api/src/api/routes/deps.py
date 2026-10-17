from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from api.catalog import Catalog
from api.jobs import JobService


async def db_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.db.sessions() as session:
        yield session


def job_service(request: Request) -> JobService:
    return request.app.state.jobs


def catalog(request: Request) -> Catalog:
    return request.app.state.catalog


Session = Annotated[AsyncSession, Depends(db_session)]
Jobs = Annotated[JobService, Depends(job_service)]
CatalogDep = Annotated[Catalog, Depends(catalog)]
