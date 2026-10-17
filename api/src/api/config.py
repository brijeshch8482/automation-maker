"""Settings from environment variables (or a local .env file)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite+aiosqlite:///./makemyexe-dev.db"
    # Public base URL of this API; routines call back to {public_base_url}/internal/...
    public_base_url: str = "http://localhost:8000"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    catalog_dir: Path = REPO_ROOT / "automations"

    # Generation: "routine" (internal phase) or "fake" (local dev without routines).
    provider: str = "fake"
    routine_spec_url: str = ""
    routine_spec_token: SecretStr = SecretStr("")
    routine_build_url: str = ""
    routine_build_token: SecretStr = SecretStr("")

    # Signs per-job callback tokens: token = HMAC(callback_token_secret, job_id).
    callback_token_secret: SecretStr = SecretStr("dev-only-change-me")
    # Shared with automation-builds Job 2, which signs /internal/build-callback.
    build_callback_secret: SecretStr = SecretStr("dev-only-change-me")

    # Windows build dispatch. Env var BUILDS_GITHUB_TOKEN, deliberately not GITHUB_TOKEN, so an
    # unrelated token is never picked up. Scope it to actions:write on the builds repo only.
    builds_github_token: SecretStr = SecretStr("")
    builds_repo: str = "brijeshch8482/automation-builds"
    builds_workflow: str = "build.yml"

    # Auth: Supabase JWT secret (HS256). dev_auth accepts "Bearer dev:<user-id>"; never in prod.
    supabase_jwt_secret: SecretStr = SecretStr("")
    supabase_jwt_audience: str = "authenticated"
    dev_auth: bool = False

    # Watchdog (minutes / days).
    spec_timeout_min: int = 15
    generation_timeout_min: int = 30
    build_timeout_min: int = 45
    watchdog_interval_s: int = 60
    max_repairs: int = 2
    unconfirmed_expiry_days: int = 30
    description_retention_days: int = 30


@lru_cache
def get_settings() -> Settings:
    return Settings()
