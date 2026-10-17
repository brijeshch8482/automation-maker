"""Deployment settings: Supabase connection strings, migrations, env parsing, startup checks."""

import asyncio

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from pydantic import SecretStr
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from api.app import check_production_settings
from api.config import Settings
from api.db import Base, engine_options
from api.migrate import upgrade

SESSION_POOLER = "postgresql://postgres.abcdefgh:p%40ss%2Fword@aws-0-ap-south-1.pooler.supabase.com:5432/postgres"


def test_session_pooler_url_becomes_asyncpg_with_ssl():
    url, options = engine_options(SESSION_POOLER)
    assert url == (
        "postgresql+asyncpg://postgres.abcdefgh:p%40ss%2Fword@"
        "aws-0-ap-south-1.pooler.supabase.com:5432/postgres"
    )
    assert options["connect_args"] == {"ssl": "require"}
    assert options["pool_pre_ping"] is True
    assert options["pool_size"] + options["max_overflow"] <= 5
    assert options["pool_recycle"] <= 300


def test_postgres_scheme_and_sslmode_query():
    url, options = engine_options("postgres://u:p@localhost:5432/db?sslmode=disable")
    assert url == "postgresql+asyncpg://u:p@localhost:5432/db"
    assert options["connect_args"] == {"ssl": "disable"}


def test_transaction_pooler_disables_prepared_statements():
    url, options = engine_options(SESSION_POOLER.replace(":5432/", ":6543/"))
    assert url.endswith(":6543/postgres?prepared_statement_cache_size=0")
    assert options["connect_args"] == {"ssl": "require", "statement_cache_size": 0}


def test_sqlite_passes_through_and_bad_urls_fail():
    assert engine_options("sqlite+aiosqlite:///x.db") == ("sqlite+aiosqlite:///x.db", {})
    with pytest.raises(ValueError, match="driver"):
        engine_options("mysql://u:p@h/db")
    with pytest.raises(ValueError, match="sslmode"):
        engine_options("postgresql://u:p@h/db?sslmode=sometimes")


def test_migrations_match_the_models_and_rerun_cleanly(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path / 'm.db'}"
    upgrade(url)
    upgrade(url)  # already at head: no-op

    async def check():
        engine = create_async_engine(url)
        async with engine.connect() as conn:
            diff = await conn.run_sync(
                lambda c: compare_metadata(MigrationContext.configure(c), Base.metadata)
            )
            tables = await conn.run_sync(lambda c: inspect(c).get_table_names())
        await engine.dispose()
        return diff, tables

    diff, tables = asyncio.run(check())
    assert diff == []
    assert set(tables) == {"jobs", "job_attempts", "alembic_version"}


def test_env_parsing(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://makemyexe.pages.dev/, http://localhost:5173")
    monkeypatch.setenv("SPEC_TIMEOUT_MIN", "")  # blank in the Render dashboard
    monkeypatch.setenv("SUPABASE_URL", "https://abcdefgh.supabase.co/")
    s = Settings(_env_file=None)
    assert s.cors_origins == ["https://makemyexe.pages.dev", "http://localhost:5173"]
    assert s.spec_timeout_min == 15
    assert s.supabase_url == "https://abcdefgh.supabase.co"
    monkeypatch.setenv("CORS_ORIGINS", '["https://a.example"]')
    assert Settings(_env_file=None).cors_origins == ["https://a.example"]


STRONG = {
    "callback_token_secret": SecretStr("a" * 64),
    "build_callback_secret": SecretStr("b" * 64),
}


def test_render_deployment_refuses_unsafe_settings(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    with pytest.raises(RuntimeError) as exc:
        check_production_settings(Settings(_env_file=None, dev_auth=True))
    message = str(exc.value)
    for problem in ("CALLBACK_TOKEN_SECRET", "BUILD_CALLBACK_SECRET", "DEV_AUTH", "Postgres"):
        assert problem in message
    check_production_settings(Settings(_env_file=None, database_url=SESSION_POOLER, **STRONG))


def test_local_dev_keeps_its_defaults(monkeypatch):
    monkeypatch.delenv("RENDER", raising=False)
    check_production_settings(Settings(_env_file=None, dev_auth=True))  # SQLite + fake: fine
    with pytest.raises(RuntimeError, match="CALLBACK_TOKEN_SECRET"):
        check_production_settings(Settings(_env_file=None, database_url=SESSION_POOLER))


def test_render_blueprint_declares_every_setting_without_values():
    import re

    from tests.conftest import REPO_ROOT

    text = (REPO_ROOT / "render.yaml").read_text(encoding="utf-8")
    entries = re.findall(r"- key: (\w+)[^\n]*\n\s+(sync: false|value: .+)", text)
    declared = {key: setting for key, setting in entries}
    assert set(declared) == {name.upper() for name in Settings.model_fields}
    with_values = {key for key, setting in declared.items() if setting.startswith("value")}
    assert with_values == {"PROVIDER", "DEV_AUTH"}
    assert 'value: "false"' in text and "value: fake" in text
    assert "healthCheckPath: /health" in text and "dockerfilePath: ./api/Dockerfile" in text
