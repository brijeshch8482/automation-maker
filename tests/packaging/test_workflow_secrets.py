"""Secret scoping in the workflows: every secret comes from a protected environment, and the
job that runs generated code has no secrets and no cache (docs/ROUTINES.md §5)."""

import json
from pathlib import Path

import pytest
import yaml

from tests.conftest import REPO_ROOT

WORKFLOWS = sorted(
    [
        *(REPO_ROOT / ".github" / "workflows").glob("*.yml"),
        *(REPO_ROOT / "builds-repo" / ".github" / "workflows").glob("*.yml"),
    ]
)


def jobs(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))["jobs"]


def text(job: dict) -> str:
    return json.dumps(job)


def secrets_used(job: dict) -> bool:
    return "secrets." in text(job).replace("secrets.GITHUB_TOKEN", "")


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.relative_to(REPO_ROOT).as_posix())
def test_every_job_with_secrets_takes_them_from_an_environment(path):
    # A repository secret reaches any job of any branch; an environment limited to main does not.
    for name, job in jobs(path).items():
        if secrets_used(job):
            assert job.get("environment"), f"{path.name}:{name} uses secrets without an environment"


def test_catalog_publish_uses_the_catalog_environment():
    ci = jobs(REPO_ROOT / ".github" / "workflows" / "ci.yml")
    assert ci["publish-catalog"]["environment"] == "catalog"
    assert [name for name, job in ci.items() if secrets_used(job)] == ["publish-catalog"]


def test_builds_repo_publish_job_has_the_secrets_and_the_build_job_none():
    build_yml = jobs(REPO_ROOT / "builds-repo" / ".github" / "workflows" / "build.yml")
    publish, build = build_yml["publish"], build_yml["build"]
    assert publish["environment"] == "publish"
    for name in (
        "BUILD_CALLBACK_SECRET",
        "R2_ACCOUNT_ID",
        "R2_SECRET_ACCESS_KEY",
        "vars.API_BASE_URL",
    ):
        assert name in text(publish)
    # Generated code runs in the build job: no secrets, no variables, no environment.
    assert not secrets_used(build)
    assert "vars." not in text(build)
    assert "environment" not in build


def test_build_job_neither_restores_nor_saves_a_cache():
    build = jobs(REPO_ROOT / "builds-repo" / ".github" / "workflows" / "build.yml")["build"]
    for step in build["steps"]:
        uses = step.get("uses", "")
        assert not uses.startswith("actions/cache"), uses
        if uses.startswith("astral-sh/setup-uv"):
            assert step["with"]["enable-cache"] is False
        if uses.startswith("actions/setup-python") or uses.startswith("actions/setup-node"):
            assert "cache" not in step.get("with", {}), uses
    assert "save-cache" not in text(build)


def test_sync_uses_the_sync_environment():
    sync = jobs(REPO_ROOT / ".github" / "workflows" / "sync-builds.yml")["sync"]
    assert sync["environment"] == "sync"
    assert "secrets.BUILDS_SYNC_TOKEN" in text(sync)
