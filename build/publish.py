"""Job 2 of build.yml: upload a passing build to R2 and send the signed build callback.

    python -m build.publish --artifact-dir art --job-id ID --attempt N --run-url URL
        --build-result success|failure|cancelled

Runs in the job that holds secrets, so it never runs generated code and treats everything in
the artifact (written by Job 1, where generated code ran) as untrusted data: names are checked,
text is cut to size, and "passed" needs both Job 1's result and report.json to agree.
Standard library only: the job installs nothing.

Settings (from the automation-builds `publish` environment): API_BASE_URL, BUILD_CALLBACK_SECRET,
R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET. With none of them set the
build is only checked and kept as a GitHub artifact (a test dispatch before hosting exists).
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

JOB_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
EXE = re.compile(r"^[A-Za-z0-9]{1,40}$")
ACCOUNT_ID = re.compile(r"[0-9a-f]{32}")
TEXT_LIMIT = {"stage": 40, "command": 1000, "test": 300, "log_tail": 8000}
MAX_UPLOAD_BYTES = 500_000_000
SETTINGS = (
    "API_BASE_URL",
    "BUILD_CALLBACK_SECRET",
    "R2_ACCOUNT_ID",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_BUCKET",
)
RETRIES, RETRY_SECONDS = 4, 30  # the free API host may be waking up


class PublishError(Exception):
    pass


def sign_body(secret: str, body: bytes) -> str:
    """Same as api.security.sign_body."""
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def read_report(artifact: Path) -> dict[str, Any]:
    try:
        data = json.loads((artifact / "report.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def failure_report(report: dict[str, Any], build_result: str) -> dict[str, str | None]:
    """The {stage, command, test, log_tail} the repair routine reads, cut to size."""
    if not report:
        return {
            "stage": "build",
            "command": "python -m build.package",
            "test": None,
            "log_tail": f"the build job ended ({build_result}) without writing report.json",
        }
    out: dict[str, str | None] = {}
    for key, limit in TEXT_LIMIT.items():
        value = report.get(key)
        out[key] = str(value)[-limit:] if value is not None else None
    if out["stage"] is None:
        out["stage"] = "build"
        out["log_tail"] = f"the build job ended ({build_result}) before every stage passed"
    return out


def passed_files(artifact: Path, report: dict[str, Any]) -> tuple[Path, Path]:
    exe = str(report.get("exe", ""))
    if not EXE.fullmatch(exe):
        raise PublishError("report.json has no valid app name")
    archive, guide = artifact / f"{exe}.zip", artifact / "Guide.pdf"
    for path in (archive, guide):
        if not path.is_file() or path.is_symlink():
            raise PublishError(f"{path.name} is missing from the build")
        if path.stat().st_size > MAX_UPLOAD_BYTES:
            raise PublishError(f"{path.name} is too large")
    return archive, guide


def r2_account_id(value: str) -> str:
    """The 32-character account ID, also when given as the S3 endpoint URL Cloudflare shows
    next to it (https://<id>.r2.cloudflarestorage.com); same as api.config's validator."""
    match = ACCOUNT_ID.search(value.strip().lower())
    return match.group(0) if match else value.strip()


def upload(path: Path, key: str, env: dict[str, str], content_type: str | None = None) -> None:
    """R2 speaks the S3 API; the aws CLI is preinstalled on GitHub's Ubuntu runners."""
    endpoint = f"https://{r2_account_id(env['R2_ACCOUNT_ID'])}.r2.cloudflarestorage.com"
    command = ["aws", "s3", "cp", str(path), f"s3://{env['R2_BUCKET']}/{key}"]
    command += ["--endpoint-url", endpoint, "--only-show-errors"]
    if content_type:
        command += ["--content-type", content_type]
    aws_env = {
        **os.environ,
        "AWS_ACCESS_KEY_ID": env["R2_ACCESS_KEY_ID"],
        "AWS_SECRET_ACCESS_KEY": env["R2_SECRET_ACCESS_KEY"],
        "AWS_DEFAULT_REGION": "auto",
    }
    result = subprocess.run(command, env=aws_env, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise PublishError(f"upload of {path.name} failed: {result.stderr.strip()[-500:]}")


def callback_request(base_url: str, secret: str, payload: dict[str, Any]) -> urllib.request.Request:
    body = json.dumps(payload, separators=(",", ":")).encode()
    return urllib.request.Request(
        base_url.rstrip("/") + "/internal/build-callback",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "X-Signature": sign_body(secret, body)},
    )


def send_callback(base_url: str, secret: str, payload: dict[str, Any]) -> int:
    request = callback_request(base_url, secret, payload)
    for attempt in range(1, RETRIES + 1):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.status
        except urllib.error.HTTPError as err:
            if err.code == 409:  # this attempt is already closed: nothing left to do
                return err.code
            if err.code < 500 or attempt == RETRIES:
                raise PublishError(f"callback refused: HTTP {err.code}") from err
        except urllib.error.URLError as err:
            if attempt == RETRIES:
                raise PublishError(f"API not reachable: {err.reason}") from err
        time.sleep(RETRY_SECONDS)
    raise PublishError("callback failed")


def publish(
    artifact: Path, job_id: str, attempt: int, run_url: str, build_result: str, env: dict
) -> dict[str, Any]:
    if not JOB_ID.fullmatch(job_id):
        raise PublishError("invalid job id")
    report = read_report(artifact)
    passed = build_result == "success" and report.get("status") == "passed"
    payload: dict[str, Any] = {
        "job_id": job_id,
        "attempt": attempt,
        "status": "passed" if passed else "failed",
        "run_url": run_url,
        "artifact_key": None,
        "guide_key": None,
        "report": None if passed else failure_report(report, build_result),
    }
    configured = [name for name in SETTINGS if env.get(name)]
    if not configured:
        print("::warning::Publishing is not configured yet; the build stays a GitHub artifact.")
        return payload
    if len(configured) < len(SETTINGS):
        missing = ", ".join(name for name in SETTINGS if not env.get(name))
        raise PublishError(f"publishing is partly configured; missing: {missing}")

    if passed:
        archive, guide = passed_files(artifact, report)
        prefix = f"jobs/{job_id}/attempt-{attempt}"
        payload["artifact_key"] = f"{prefix}/{archive.name}"
        payload["guide_key"] = f"{prefix}/Guide.pdf"
        upload(archive, payload["artifact_key"], env)
        upload(guide, payload["guide_key"], env)
    status = send_callback(env["API_BASE_URL"], env["BUILD_CALLBACK_SECRET"], payload)
    print(f"callback sent: {payload['status']} (HTTP {status})")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m build.publish", description=__doc__)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--attempt", type=int, required=True)
    parser.add_argument("--run-url", required=True)
    parser.add_argument("--build-result", required=True)
    args = parser.parse_args(argv)
    env = {name: os.environ.get(name, "") for name in SETTINGS}
    try:
        payload = publish(
            args.artifact_dir, args.job_id, args.attempt, args.run_url, args.build_result, env
        )
    except PublishError as err:
        print(f"::error::{err}")
        return 1
    print(json.dumps({k: v for k, v in payload.items() if k != "report"}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
