"""The callback build.publish sends is accepted by the real API (same signature and body)."""

import json

import pytest

from build import publish
from tests.api.conftest import BUILD_SECRET

pytestmark = pytest.mark.anyio


async def send(ctx, payload):
    request = publish.callback_request("http://test", BUILD_SECRET, payload)
    return await ctx.client.post(
        "/internal/build-callback", content=request.data, headers=dict(request.header_items())
    )


async def test_published_pass_makes_the_job_ready(ctx, tmp_path, monkeypatch):
    job_id = await ctx.create_job()
    await ctx.to_building(job_id)
    folder = tmp_path / "artifact"
    folder.mkdir()
    (folder / "report.json").write_text(json.dumps({"status": "passed", "exe": "MakePDF"}))
    (folder / "MakePDF.zip").write_bytes(b"zip")
    (folder / "Guide.pdf").write_bytes(b"pdf")
    settings = dict.fromkeys(publish.SETTINGS, "x") | {"BUILD_CALLBACK_SECRET": BUILD_SECRET}
    sent = []
    monkeypatch.setattr(publish, "upload", lambda *a: None)
    monkeypatch.setattr(publish, "send_callback", lambda url, secret, p: sent.append(p) or 204)

    payload = publish.publish(folder, job_id, 0, "https://run/1", "success", settings)
    r = await send(ctx, sent[0])
    assert r.status_code == 204, r.text
    job = await ctx.get_job(job_id)
    assert job["state"] == "ready"
    assert payload["artifact_key"] == f"jobs/{job_id}/attempt-0/MakePDF.zip"


async def test_published_failure_starts_a_repair(ctx, tmp_path):
    job_id = await ctx.create_job()
    await ctx.to_building(job_id)
    report = {"status": "failed", "stage": "launch_check", "command": "X.exe", "log_tail": "boom"}
    payload = {
        "job_id": job_id,
        "attempt": 0,
        "status": "failed",
        "run_url": "u",
        "artifact_key": None,
        "guide_key": None,
        "report": publish.failure_report(report, "failure"),
    }
    r = await send(ctx, payload)
    assert r.status_code == 204, r.text
    assert (await ctx.get_job(job_id))["state"] == "repairing"
    assert ctx.provider.calls[-1][2]["report"]["stage"] == "launch_check"
