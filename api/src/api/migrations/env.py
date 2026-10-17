"""Alembic environment: async engine, URL from settings (or the caller), same options as the app."""

from __future__ import annotations

import asyncio

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from api.config import get_settings
from api.db import Base, engine_options

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    return config.attributes.get("database_url") or get_settings().database_url


def run_migrations_offline() -> None:
    url, _ = engine_options(_url())
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def _run(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=connection.dialect.name == "sqlite",  # SQLite can't ALTER most things
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    url, options = engine_options(_url())
    # One short-lived connection: no pool, but the same SSL / pooler arguments as the app.
    engine = create_async_engine(
        url, poolclass=pool.NullPool, connect_args=options.get("connect_args", {})
    )
    async with engine.connect() as connection:
        await connection.run_sync(_run)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
