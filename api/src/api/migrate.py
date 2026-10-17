"""Apply database migrations: `python -m api.migrate` (the container runs it before uvicorn).

Render's pre-deploy command needs a paid instance, so on the free plan the start command
runs this first. Alembic's version table makes it a no-op when the schema is current.
"""

from __future__ import annotations

import logging

from alembic import command
from alembic.config import Config

from api.config import get_settings


def alembic_config(database_url: str | None = None) -> Config:
    config = Config()
    config.set_main_option("script_location", "api:migrations")
    config.attributes["database_url"] = database_url or get_settings().database_url
    return config


def upgrade(database_url: str | None = None, revision: str = "head") -> None:
    command.upgrade(alembic_config(database_url), revision)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    from api.app import check_production_settings

    # Fail with the clear message before touching a database that may be the wrong one.
    check_production_settings(get_settings())
    upgrade()


if __name__ == "__main__":
    main()
