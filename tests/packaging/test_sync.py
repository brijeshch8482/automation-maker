"""builds-repo/sync.py: what goes to automation-builds/main, and what never does."""

import importlib.util

import pytest

from tests.conftest import REPO_ROOT

spec = importlib.util.spec_from_file_location("builds_sync", REPO_ROOT / "builds-repo" / "sync.py")
sync_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync_module)


def test_sync_copies_the_snapshot_and_keeps_other_files(tmp_path):
    target = tmp_path / "automation-builds"
    (target / ".git").mkdir(parents=True)
    (target / "engine" / "old_module.py").parent.mkdir()
    (target / "engine" / "old_module.py").write_text("stale")
    (target / "jobs" / "x").mkdir(parents=True)
    (target / "jobs" / "x" / "spec.json").write_text("{}")

    copied = sync_module.sync(target, "engine-v0.2.0", "0123456789abcdef0123")

    assert ".github/workflows/build.yml" in copied
    for path in (
        "engine/src/engine/runner.py",
        "spec/src/spec/catalog.py",
        "build/package.py",
        "build/publish.py",
        "tools/validate_spec/__main__.py",
        "uv.lock",
        "pyproject.toml",
        "README.md",
        ".gitignore",
        "CLAUDE.md",
        "docs/SPEC_GUIDE.md",
        "examples/catalog/invoice-generator/spec.json",
        "examples/custom/word-count/custom_step.py",
        "examples/custom/word-count/test_custom_step.py",
        "tools/check_job/__main__.py",
    ):
        assert (target / path).is_file(), path
    assert not (target / "engine" / "old_module.py").exists()  # managed paths are replaced
    assert (target / "jobs" / "x" / "spec.json").is_file()  # everything else stays
    assert (target / "ENGINE_VERSION").read_text() == "engine-v0.2.0 0123456789ab\n"
    # Only what a build needs: no API code, web, catalog, tests or caches.
    assert sorted(p.name for p in (target / "api").iterdir()) == ["pyproject.toml"]
    for absent in ("web", "automations", "tests", ".github/workflows/ci.yml"):
        assert not (target / absent).exists(), absent
    assert [p.name for p in (target / "docs").iterdir()] == ["SPEC_GUIDE.md"]
    assert not list(target.rglob("__pycache__"))


def test_sync_needs_a_checkout(tmp_path):
    with pytest.raises(SystemExit, match="not a git checkout"):
        sync_module.sync(tmp_path, "v", "abc")
