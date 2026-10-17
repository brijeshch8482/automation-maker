"""Publish the packaged catalog apps to R2 and write catalog/manifest.json (CI, main only).

    python3 -m build.publish_catalog --artifacts artifacts --commit <sha>

`artifacts` holds one folder per automation, app-<id>/, as uploaded by CI's package jobs:
<Exe>.zip, Guide.pdf and report.json. Every app is checked before anything is uploaded, and the
manifest goes last, so the API never points at a file that isn't there. Standard library only.

Settings (GitHub secrets of automation-maker): R2_ACCOUNT_ID, R2_ACCESS_KEY_ID,
R2_SECRET_ACCESS_KEY, R2_BUCKET; a token with Object Read & Write on that bucket. With none of
them set, the apps are only checked (downloads not switched on yet).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from build.publish import EXE, MAX_UPLOAD_BYTES, PublishError, upload

R2_SETTINGS = ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET")
AUTOMATION_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
VERSION = re.compile(r"^\d+\.\d+\.\d+$")
MANIFEST_KEY = "catalog/manifest.json"


def collect(artifacts: Path) -> list[dict[str, Any]]:
    """One checked entry per app-<id>/ folder; any problem stops the release."""
    apps = []
    for folder in sorted(artifacts.glob("app-*")):
        automation = folder.name.removeprefix("app-")
        try:
            report = json.loads((folder / "report.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as err:
            raise PublishError(f"{folder.name}: report.json is missing or broken") from err
        if report.get("status") != "passed":
            raise PublishError(f"{folder.name}: the build did not pass ({report.get('stage')})")
        if report.get("automation") != automation or not AUTOMATION_ID.fullmatch(automation):
            raise PublishError(f"{folder.name}: report.json names another automation")
        version, exe = str(report.get("version", "")), str(report.get("exe", ""))
        if not VERSION.fullmatch(version) or not EXE.fullmatch(exe):
            raise PublishError(f"{folder.name}: invalid version or app name")
        archive, guide = folder / f"{exe}.zip", folder / "Guide.pdf"
        for path in (archive, guide):
            if not path.is_file() or path.stat().st_size > MAX_UPLOAD_BYTES:
                raise PublishError(f"{folder.name}: {path.name} is missing or too large")
        apps.append(
            {
                "id": automation,
                "version": version,
                "exe": exe,
                "archive": archive,
                "guide": guide,
                "engine_version": report.get("engine_version"),
            }
        )
    if not apps:
        raise PublishError(f"no app-* folders in {artifacts}")
    return apps


def manifest(apps: list[dict[str, Any]], commit: str, now: datetime) -> dict[str, Any]:
    built_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    entries = {}
    for app in apps:
        prefix = f"catalog/{app['id']}/{app['version']}"
        entries[app["id"]] = {
            "version": app["version"],
            "exe": app["exe"],
            "zip": f"{prefix}/{app['exe']}.zip",
            "zip_bytes": app["archive"].stat().st_size,
            "guide": f"{prefix}/Guide.pdf",
            "guide_bytes": app["guide"].stat().st_size,
            "built_at": built_at,
            "commit": commit[:12],
            "engine_version": app["engine_version"],
        }
    return {"generated_at": built_at, "automations": entries}


def publish(artifacts: Path, commit: str, env: dict[str, str], now: datetime) -> dict[str, Any]:
    apps = collect(artifacts)
    result = manifest(apps, commit, now)
    configured = [name for name in R2_SETTINGS if env.get(name)]
    if not configured:
        print("::warning::R2 is not configured; the catalog apps were checked, not published.")
        return result
    if len(configured) < len(R2_SETTINGS):
        missing = ", ".join(name for name in R2_SETTINGS if not env.get(name))
        raise PublishError(f"R2 is partly configured; missing: {missing}")
    for app in apps:
        entry = result["automations"][app["id"]]
        upload(app["archive"], entry["zip"], env, "application/zip")
        upload(app["guide"], entry["guide"], env, "application/pdf")
        print(f"uploaded {app['id']} {app['version']}")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "manifest.json"
        path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        upload(path, MANIFEST_KEY, env, "application/json")
    print(f"published {MANIFEST_KEY} with {len(apps)} apps")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m build.publish_catalog", description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--commit", default="")
    args = parser.parse_args(argv)
    env = {name: os.environ.get(name, "") for name in R2_SETTINGS}
    try:
        result = publish(args.artifacts, args.commit, env, datetime.now(UTC))
    except PublishError as err:
        print(f"::error::{err}")
        return 1
    for app_id, entry in result["automations"].items():
        print(f"{app_id}: {entry['zip']} ({entry['zip_bytes'] / 1_000_000:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
