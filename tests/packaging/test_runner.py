"""build.runner (the shared Runner) and build.pack_check (Pack Job 1), without PyInstaller."""

import json
import shutil
import zipfile

import yaml

from build import runner
from build.pack_check import PackCheck
from engine.blocks import IMPLEMENTATIONS
from engine.keys import parse_keys
from spec.fingerprint import spec_sha256
from tests.conftest import REPO_ROOT
from tools.check_job import CODE_MODULES

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "jobs" / "word-count"


def test_runner_bundles_every_block_and_everything_custom_code_may_import():
    modules = set(runner.RUNNER_MODULES)
    assert {target.split(":")[0] for target in IMPLEMENTATIONS.values()} <= modules
    assert CODE_MODULES - {"__future__"} <= modules
    assert "engine.custom_api" in modules


def test_runner_trusts_the_committed_keys_plus_extra_ones(tmp_path):
    extra = tmp_path / "ci.json"
    extra.write_text(json.dumps({"ci-test": "22" * 32}))
    keys = runner.merged_keys(extra)
    assert keys["ci-test"] == "22" * 32
    assert runner.merged_keys(None).keys() == keys.keys() - {"ci-test"}


def test_tampered_copy_differs_only_in_spec(tmp_path):
    original = tmp_path / "app.mmx"
    with zipfile.ZipFile(original, "w") as archive:
        archive.writestr("manifest.json", "{}")
        archive.writestr("spec.json", '{"id": "x"}')
    changed = runner._tamper(original, tmp_path / "changed.mmx")
    with zipfile.ZipFile(original) as a, zipfile.ZipFile(changed) as b:
        assert a.read("manifest.json") == b.read("manifest.json")
        assert a.read("spec.json") != b.read("spec.json")


def test_pack_check_passes_the_custom_job_and_makes_its_guide(tmp_path):
    report = PackCheck(FIXTURE, tmp_path / "out", None).run()
    assert report.status == "passed", report.log_tail
    assert [s["name"] for s in report.stages] == ["validate", "check_job", "guide", "guide_pdf"]
    assert (tmp_path / "out" / "Guide.pdf").read_bytes().startswith(b"%PDF")
    assert json.loads((tmp_path / "out" / "report.json").read_text())["status"] == "passed"


def test_pack_check_refuses_an_unconfirmed_spec(tmp_path):
    report = PackCheck(FIXTURE, tmp_path / "out", "0" * 64).run()
    assert (report.status, report.stage, report.command) == (
        "failed",
        "validate",
        "spec fingerprint check",
    )
    confirmed = spec_sha256(json.loads((FIXTURE / "spec.json").read_text(encoding="utf-8")))
    assert PackCheck(FIXTURE, tmp_path / "ok", confirmed)._validate().id == "word-count"


def test_pack_check_reports_the_failing_check(tmp_path):
    app = tmp_path / "app"
    shutil.copytree(FIXTURE, app)
    (app / "custom_step.py").write_text("import os\n\n\ndef run(ctx):\n    return None\n")
    report = PackCheck(app, tmp_path / "out", None).run()
    assert (report.status, report.stage) == ("failed", "check_job")
    assert "import os is not allowed" in report.log_tail


def test_ci_builds_packs_on_linux_and_the_runner_on_windows():
    jobs = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text())["jobs"]
    packs, runner_job = jobs["packs"], jobs["runner"]
    assert packs["runs-on"] == "ubuntu-latest" and runner_job["runs-on"] == "windows-latest"
    assert runner_job["needs"] == "packs"
    text = json.dumps(packs)
    assert "build.pack_check" in text and "build.pack make" in text
    # The throwaway private key never leaves the packs job; only the public half does.
    assert 'rm -rf \\"$RUNNER_TEMP/keys\\"' in text
    upload = next(s for s in packs["steps"] if s.get("uses", "").startswith("actions/upload"))
    assert "keys" not in upload["with"]["path"].replace("ci-keys.json", "")
    run = json.dumps(runner_job)
    assert "build.runner" in run and "--launch-check" in run and "--check-pack" in run


def test_largest_parts_groups_by_folder(tmp_path):
    (tmp_path / "_internal" / "PySide6" / "plugins").mkdir(parents=True)
    (tmp_path / "MakeMyEXE.exe").write_bytes(b"x" * 3_000_000)
    (tmp_path / "_internal" / "PySide6" / "Qt6Gui.dll").write_bytes(b"x" * 2_000_000)
    (tmp_path / "_internal" / "PySide6" / "plugins" / "a.dll").write_bytes(b"x" * 600_000)
    (tmp_path / "_internal" / "PySide6" / "plugins" / "b.dll").write_bytes(b"x" * 600_000)
    assert runner.largest_parts(tmp_path) == {
        "MakeMyEXE.exe": 3.0,
        "_internal/PySide6/Qt6Gui.dll": 2.0,
        "_internal/PySide6/plugins": 1.2,
    }


def test_committed_keys_are_valid():
    # A file the Runner can't read would make it trust nothing and refuse every pack.
    keys = parse_keys((REPO_ROOT / "build" / "trusted_keys.json").read_text(encoding="utf-8"))
    assert {"catalog-1", "jobs-1"} <= set(keys)
    assert all(len(key) == 32 for key in keys.values())
