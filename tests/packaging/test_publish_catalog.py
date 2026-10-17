"""build.publish_catalog: checks every app first, uploads, and writes the manifest last."""

import json
from datetime import UTC, datetime

import pytest

from build import publish_catalog
from build.publish import PublishError
from tests.conftest import REPO_ROOT

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
R2 = {
    "R2_ACCOUNT_ID": "acct",
    "R2_ACCESS_KEY_ID": "key",
    "R2_SECRET_ACCESS_KEY": "secret",
    "R2_BUCKET": "makemyexe-builds",
}


def app_folder(root, automation="make-pdf", exe="MakePDF", **report):
    folder = root / f"app-{automation}"
    folder.mkdir(parents=True)
    report = {"status": "passed", "automation": automation, "version": "1.0.0", "exe": exe} | report
    (folder / "report.json").write_text(json.dumps(report))
    (folder / f"{exe}.zip").write_bytes(b"z" * 1000)
    (folder / "Guide.pdf").write_bytes(b"%PDF" + b"g" * 96)
    return folder


@pytest.fixture
def uploads(monkeypatch):
    done = []
    monkeypatch.setattr(
        publish_catalog,
        "upload",
        lambda path, key, env, content_type=None: done.append((key, content_type)),
    )
    return done


def test_publishes_every_app_then_the_manifest(tmp_path, uploads):
    app_folder(tmp_path)
    app_folder(tmp_path, "pdf-merge", "PDFMerge")
    result = publish_catalog.publish(tmp_path, "0123456789abcdef", R2, NOW)
    assert uploads == [
        ("catalog/make-pdf/1.0.0/MakePDF.zip", "application/zip"),
        ("catalog/make-pdf/1.0.0/Guide.pdf", "application/pdf"),
        ("catalog/pdf-merge/1.0.0/PDFMerge.zip", "application/zip"),
        ("catalog/pdf-merge/1.0.0/Guide.pdf", "application/pdf"),
        ("catalog/manifest.json", "application/json"),  # last: never points at a missing file
    ]
    entry = result["automations"]["make-pdf"]
    assert entry["zip_bytes"] == 1000
    assert entry["guide_bytes"] == 100
    assert entry["commit"] == "0123456789ab"
    assert entry["built_at"] == "2026-10-17T12:00:00Z"


def test_manifest_shape_matches_what_the_api_reads(tmp_path):
    from api.storage import MANIFEST_KEY

    assert publish_catalog.MANIFEST_KEY == MANIFEST_KEY
    app_folder(tmp_path)
    entry = publish_catalog.manifest(publish_catalog.collect(tmp_path), "abc", NOW)["automations"][
        "make-pdf"
    ]
    assert {"version", "zip", "zip_bytes", "guide", "built_at"} <= set(entry)


@pytest.mark.parametrize(
    ("report", "message"),
    [
        ({"status": "failed", "stage": "smoke_test"}, "did not pass"),
        ({"automation": "other"}, "another automation"),
        ({"version": "1.0"}, "invalid version"),
        ({"exe": "../evil"}, "invalid version or app name"),
    ],
)
def test_a_bad_build_stops_the_release_before_any_upload(tmp_path, uploads, report, message):
    app_folder(tmp_path)
    second = app_folder(tmp_path, "pdf-merge", "PDFMerge")
    data = json.loads((second / "report.json").read_text()) | report
    (second / "report.json").write_text(json.dumps(data))
    with pytest.raises(PublishError, match=message):
        publish_catalog.publish(tmp_path, "abc", R2, NOW)
    assert uploads == []


def test_missing_files(tmp_path, uploads):
    (app_folder(tmp_path) / "Guide.pdf").unlink()
    with pytest.raises(PublishError, match=r"Guide\.pdf is missing"):
        publish_catalog.publish(tmp_path, "abc", R2, NOW)
    with pytest.raises(PublishError, match="no app-"):
        publish_catalog.publish(tmp_path / "empty", "abc", R2, NOW)


def test_without_r2_the_apps_are_only_checked(tmp_path, uploads, capsys):
    app_folder(tmp_path)
    publish_catalog.publish(tmp_path, "abc", dict.fromkeys(R2, ""), NOW)
    assert uploads == []
    assert "not configured" in capsys.readouterr().out
    with pytest.raises(PublishError, match="missing: R2_BUCKET"):
        publish_catalog.publish(tmp_path, "abc", {**R2, "R2_BUCKET": ""}, NOW)


def test_ci_publishes_only_from_main_after_tests_and_runs_no_app_code():
    ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    job = ci.split("\n  publish-catalog:")[1].split("\n  web:")[0]
    assert "github.event_name == 'push' && github.ref == 'refs/heads/main'" in job
    assert "needs: [test, package]" in job
    assert "python3 -m build.publish_catalog" in job
    for forbidden in ("uv sync", "build.package", "pull_request_target"):
        assert forbidden not in job
    # The R2 secrets appear in this job only.
    assert ci.count("secrets.R2_") == job.count("secrets.R2_") == 4
