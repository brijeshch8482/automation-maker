"""build.package without PyInstaller: names, bundled files, imports, trimming, the report."""

import json
import re
import sys
from pathlib import Path

import pytest

from build import package
from build.package import (
    Packager,
    StageFailed,
    excludes,
    exe_name,
    hidden_imports,
    run,
    stage_app,
    trim,
)
from engine.loader import load_spec
from tests.conftest import AUTOMATIONS_DIR, REPO_ROOT


def spec_of(automation: str):
    return load_spec(AUTOMATIONS_DIR / automation / "spec.json").spec


@pytest.mark.parametrize(
    ("title", "name"),
    [
        ("Make PDF", "MakePDF"),
        ("Invoice Generator", "InvoiceGenerator"),
        ("bulk rename", "BulkRename"),
        ("GST-bill (v2) / रसीद", "GSTBillV2"),
        ("रसीद", "Automation"),
    ],
)
def test_exe_name(title, name):
    assert exe_name(title) == name


def test_hidden_imports_are_the_blocks_the_spec_uses():
    assert hidden_imports(spec_of("make-pdf"), AUTOMATIONS_DIR / "make-pdf") == [
        "engine.blocks.files",
        "engine.blocks.makepdf",
    ]
    invoice = hidden_imports(spec_of("invoice-generator"), AUTOMATIONS_DIR / "invoice-generator")
    assert "engine.blocks.template" in invoice
    assert "engine.blocks.makepdf" not in invoice


def test_hidden_imports_include_what_custom_step_imports(tmp_path):
    (tmp_path / "custom_step.py").write_text(
        "import csv, json as j\nfrom datetime import date\nfrom . import helper\n"
        "def run(ctx):\n    import statistics\n",
        encoding="utf-8",
    )
    modules = hidden_imports(spec_of("pdf-merge"), tmp_path)
    assert {"csv", "json", "datetime", "statistics"} <= set(modules)
    assert "helper" not in modules


def test_font_libraries_only_for_apps_that_make_pdfs():
    assert "fontTools" in excludes(spec_of("pdf-merge"))
    assert "fontTools" in excludes(spec_of("bulk-rename"))
    assert "fontTools" not in excludes(spec_of("make-pdf"))
    assert "uharfbuzz" not in excludes(spec_of("invoice-generator"))
    assert "cryptography" in excludes(spec_of("make-pdf"))


def test_stage_app_bundles_only_spec_samples_and_custom_step(tmp_path):
    src = tmp_path / "job"
    (src / "samples" / "__pycache__").mkdir(parents=True)
    (src / "spec.json").write_text("{}")
    (src / "custom_step.py").write_text("def run(ctx): ...")
    (src / "test_custom_step.py").write_text("def test(): ...")
    (src / "samples" / "a.pdf").write_bytes(b"%PDF")
    (src / "samples" / "__pycache__" / "x.pyc").write_bytes(b"")
    (src / "notes.txt").write_text("not bundled")
    dest = stage_app(src, tmp_path / "app")
    files = sorted(p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file())
    assert files == ["custom_step.py", "samples/a.pdf", "spec.json"]


def test_trim_removes_only_listed_qt_parts(tmp_path):
    internal = tmp_path / "_internal"
    keep = [
        "PySide6/Qt6Core.dll",
        "PySide6/Qt6Widgets.dll",
        "PySide6/plugins/platforms/qwindows.dll",
        "PySide6/plugins/imageformats/qsvg.dll",
    ]
    drop = [
        "PySide6/translations/qt_de.qm",
        "PySide6/opengl32sw.dll",
        "PySide6/Qt6Network.dll",
        "PySide6/plugins/tls/qschannelbackend.dll",
    ]
    for rel in keep + drop:
        (internal / rel).parent.mkdir(parents=True, exist_ok=True)
        (internal / rel).write_bytes(b"x")
    removed = trim(internal)
    assert all((internal / rel).exists() for rel in keep)
    assert not any((internal / rel).exists() for rel in drop)
    assert "PySide6/opengl32sw.dll" in removed


def test_run_reports_the_end_of_the_log(tmp_path, monkeypatch):
    log = tmp_path / "build.log"
    monkeypatch.setenv("SECRET_THING", "x")
    code = (
        "import os, sys; print('line ' * 3000); "
        "print('MAKEMYEXE', os.environ.get('SECRET_THING')); sys.exit(4)"
    )
    with pytest.raises(StageFailed) as err:
        run("smoke_test", [sys.executable, "-c", code], log, {"SECRET_THING": None})
    assert err.value.stage == "smoke_test"
    assert err.value.log_tail.rstrip().endswith("MAKEMYEXE None")  # the variable was removed
    assert len(err.value.log_tail) <= package.LOG_TAIL_BYTES
    run("guide", [sys.executable, "-c", "print('ok')"], log)  # exit 0: no error


def test_invalid_spec_fails_at_validate_with_a_report(tmp_path, capsys):
    app = tmp_path / "job"
    app.mkdir()
    (app / "spec.json").write_text(json.dumps({"id": "x"}))
    assert package.main([str(app), "--out", str(tmp_path / "out")]) == 1
    report = json.loads((tmp_path / "out" / "report.json").read_text())
    assert report["status"] == "failed"
    assert report["stage"] == "validate"
    assert "title" in report["log_tail"]
    assert "validate failed" in capsys.readouterr().err


def test_a_failing_stage_stops_the_build_and_is_reported(tmp_path, monkeypatch):
    def fake_run(stage, cmd, log, env=None):
        raise StageFailed(stage, "pyinstaller ...", "ImportError: no module named x")

    monkeypatch.setattr(package, "run", fake_run)
    report = Packager(AUTOMATIONS_DIR / "pdf-merge", tmp_path / "out", launch_check=False).run()
    assert (report.status, report.stage) == ("failed", "package")
    assert report.exe == "PDFMerge"
    assert report.log_tail == "ImportError: no module named x"
    assert [s["name"] for s in report.stages] == ["validate", "package"]
    assert json.loads((tmp_path / "out" / "report.json").read_text())["stage"] == "package"


def test_a_bug_in_a_stage_is_still_reported(tmp_path, monkeypatch):
    def broken(self, spec):
        raise KeyError("oops")

    monkeypatch.setattr(Packager, "_package", broken)
    report = Packager(AUTOMATIONS_DIR / "pdf-merge", tmp_path / "out", launch_check=False).run()
    assert (report.status, report.stage) == ("failed", "package")
    assert "KeyError" in report.log_tail


def test_ci_packages_every_catalog_automation():
    ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    listed = re.search(r"automation: \[([^\]]+)\]", ci).group(1)
    names = sorted(n.strip() for n in listed.split(","))
    assert names == sorted(p.parent.name for p in AUTOMATIONS_DIR.glob("*/spec.json"))


def test_builds_repo_workflow_runs_the_same_command():
    ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    build = (REPO_ROOT / "builds-repo" / ".github" / "workflows" / "build.yml").read_text()
    install = "uv sync --locked --no-dev --only-group build --inexact"
    for workflow in (ci, build):
        assert "python -m build.package" in workflow
        assert "--launch-check" in workflow
        assert install in workflow
    # Generated code never sees a secret: the build job has none, and drops the git token.
    build_job = build.split("\n  publish:")[0]
    assert "${{ secrets." not in build_job
    assert "extraheader" in build_job


def test_entry_point_exists():
    assert Path(package.__file__).with_name("entry.py").is_file()
