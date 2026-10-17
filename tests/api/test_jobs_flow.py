import pytest

from api.providers import FireRejected, FireUnknown, RetryLater
from tests.api.conftest import ALICE, BOB, invoice_spec

pytestmark = pytest.mark.anyio


# --- spec phase -------------------------------------------------------------------------


async def test_create_job_masks_pii_and_fires_spec(ctx):
    job_id = await ctx.create_job("Bill Asha at 9876543210 every month with GST invoices")
    job = await ctx.get_job(job_id)

    assert job["state"] == "spec_requested"
    assert job["description"] == "Bill Asha at [phone number] every month with GST invoices"
    assert [(a["mode"], a["status"]) for a in job["attempts"]] == [("spec", "open")]
    assert job["attempts"][0]["session_url"].startswith("https://claude.ai/code/")

    mode, fired, data = ctx.provider.calls[0]
    assert mode == "spec"
    assert fired.job_id == job_id and fired.revision == 0
    assert fired.callback_url == "https://api.test/internal/routine-callback"
    assert "9876543210" not in data["description"]
    assert data["previous_spec"] is None and data["answers"] == []


async def test_description_too_short(ctx):
    r = await ctx.client.post("/jobs", json={"description": "pdf"}, headers=ALICE)
    assert r.status_code == 422


async def test_other_users_cannot_see_a_job(ctx):
    job_id = await ctx.create_job()
    assert (await ctx.client.get(f"/jobs/{job_id}", headers=BOB)).status_code == 404
    assert (await ctx.client.post(f"/jobs/{job_id}/confirm", headers=BOB)).status_code == 404
    mine = (await ctx.client.get("/me/jobs", headers=ALICE)).json()
    assert [j["id"] for j in mine] == [job_id]
    assert (await ctx.client.get("/me/jobs", headers=BOB)).json() == []


async def test_spec_ready(ctx):
    job_id = await ctx.create_job()
    await ctx.spec_ready(job_id)
    job = await ctx.get_job(job_id)
    assert job["state"] == "spec_ready"
    assert job["spec"]["id"] == "invoice-generator"
    assert job["assumptions"] == ["GST is 18% unless changed"]
    assert job["questions"] == ["Do you need a discount column?"]
    assert job["attempts"][0]["status"] == "ok"
    mine = (await ctx.client.get("/me/jobs", headers=ALICE)).json()
    assert mine[0]["title"] == "Invoice Generator"


async def test_callback_with_bad_token_is_rejected(ctx):
    job_id = await ctx.create_job()
    r = await ctx.routine_callback(job_id, token="wrong", mode="spec", status="ok")
    assert r.status_code == 401
    other = await ctx.create_job()
    # A token for another job doesn't work either.
    from api.security import callback_token
    from tests.api.conftest import CALLBACK_SECRET

    r = await ctx.routine_callback(
        job_id, token=callback_token(CALLBACK_SECRET, other), mode="spec", status="ok"
    )
    assert r.status_code == 401


async def test_callback_for_unknown_job(ctx):
    r = await ctx.routine_callback("job_01JAAAAAAAAAAAAAAAAAAAAAAA", mode="spec", status="ok")
    assert r.status_code == 404


async def test_duplicate_spec_callback_is_ignored(ctx):
    job_id = await ctx.create_job()
    await ctx.spec_ready(job_id)
    r = await ctx.routine_callback(job_id, mode="spec", revision=0, status="failed", reason="x")
    assert r.status_code == 204
    assert (await ctx.get_job(job_id))["state"] == "spec_ready"


async def test_callback_for_wrong_revision_or_mode_is_rejected(ctx):
    job_id = await ctx.create_job()
    r = await ctx.routine_callback(job_id, mode="spec", revision=3, status="ok", spec={})
    assert r.status_code == 409
    r = await ctx.routine_callback(job_id, mode="build", attempt=0, status="ok")
    assert r.status_code == 409
    assert (await ctx.get_job(job_id))["state"] == "spec_requested"


async def test_invalid_spec_from_routine_fails_the_job(ctx):
    job_id = await ctx.create_job()
    spec = invoice_spec()
    spec["steps"][0]["block"] = "nope.nope"
    r = await ctx.routine_callback(job_id, mode="spec", revision=0, status="ok", spec=spec)
    assert r.status_code == 204
    job = await ctx.get_job(job_id)
    assert job["state"] == "failed"
    assert "validation" in job["failure_reason"]


async def test_spec_failed(ctx):
    job_id = await ctx.create_job()
    r = await ctx.routine_callback(
        job_id, mode="spec", revision=0, status="failed", reason="too vague"
    )
    assert r.status_code == 204
    job = await ctx.get_job(job_id)
    assert job["state"] == "failed"
    assert "too vague" in job["failure_reason"]
    # The job is closed now: a callback for an attempt that never existed is rejected.
    r = await ctx.routine_callback(job_id, mode="spec", revision=1, status="ok", spec={})
    assert r.status_code == 409


async def test_answers_start_a_revision(ctx):
    job_id = await ctx.create_job()
    await ctx.spec_ready(job_id)
    answers = [{"question": "Do you need a discount column?", "answer": "Yes, call 9876543210"}]
    r = await ctx.client.post(f"/jobs/{job_id}/answers", json={"answers": answers}, headers=ALICE)
    assert r.status_code == 202
    assert r.json()["state"] == "spec_requested"
    assert r.json()["revision"] == 1

    mode, fired, data = ctx.provider.calls[-1]
    assert (mode, fired.revision) == ("spec", 1)
    assert data["previous_spec"]["id"] == "invoice-generator"
    assert data["answers"] == [
        {"question": "Do you need a discount column?", "answer": "Yes, call [phone number]"}
    ]

    # A late callback for revision 0 is a duplicate; revision 1 completes the round.
    stale = await ctx.routine_callback(job_id, mode="spec", revision=0, status="ok")
    assert stale.status_code == 204
    assert (await ctx.get_job(job_id))["state"] == "spec_requested"
    await ctx.spec_ready(job_id, revision=1)
    assert (await ctx.get_job(job_id))["state"] == "spec_ready"


async def test_answers_need_spec_ready(ctx):
    job_id = await ctx.create_job()
    answers = [{"question": "q", "answer": "a"}]
    r = await ctx.client.post(f"/jobs/{job_id}/answers", json={"answers": answers}, headers=ALICE)
    assert r.status_code == 409


async def test_save_spec(ctx):
    job_id = await ctx.create_job()
    await ctx.spec_ready(job_id)
    spec = invoice_spec()
    spec["title"] = "My Invoices"
    r = await ctx.client.put(f"/jobs/{job_id}/spec", json={"spec": spec}, headers=ALICE)
    assert r.status_code == 200
    assert r.json()["spec"]["title"] == "My Invoices"

    spec["steps"][3]["args"]["folder"] = "@settings.nope"
    r = await ctx.client.put(f"/jobs/{job_id}/spec", json={"spec": spec}, headers=ALICE)
    assert r.status_code == 422
    assert "steps[3].args.folder" in r.json()["detail"]["issues"][0]
    assert (await ctx.get_job(job_id))["spec"]["title"] == "My Invoices"


# --- build phase ------------------------------------------------------------------------


async def test_confirm_fires_build(ctx):
    job_id = await ctx.create_job()
    await ctx.spec_ready(job_id)
    r = await ctx.client.post(f"/jobs/{job_id}/confirm", headers=ALICE)
    assert r.status_code == 202
    assert r.json()["state"] == "generating"
    mode, fired, data = ctx.provider.calls[-1]
    assert (mode, fired.attempt) == ("build", 0)
    assert data["spec"]["id"] == "invoice-generator"
    # Confirming twice is a conflict.
    assert (await ctx.client.post(f"/jobs/{job_id}/confirm", headers=ALICE)).status_code == 409


async def test_confirm_needs_a_spec(ctx):
    job_id = await ctx.create_job()
    assert (await ctx.client.post(f"/jobs/{job_id}/confirm", headers=ALICE)).status_code == 409


async def test_generation_done_dispatches_windows_build(ctx):
    job_id = await ctx.create_job()
    await ctx.to_building(job_id)
    job = await ctx.get_job(job_id)
    assert job["state"] == "building"
    assert ctx.dispatcher.calls == [(job_id, f"claude/job-{job_id}", 0)]


async def test_callback_with_bad_branch_is_rejected(ctx):
    job_id = await ctx.create_job()
    await ctx.spec_ready(job_id)
    await ctx.client.post(f"/jobs/{job_id}/confirm", headers=ALICE)
    r = await ctx.routine_callback(
        job_id, mode="build", attempt=0, status="ok", branch="main", commit_sha="abc1234"
    )
    assert r.status_code == 422
    assert ctx.dispatcher.calls == []


async def test_dispatch_failure_fails_the_job(ctx):
    ctx.dispatcher.fail = True
    job_id = await ctx.create_job()
    await ctx.to_building(job_id)
    job = await ctx.get_job(job_id)
    assert job["state"] == "failed"
    assert "Windows build" in job["failure_reason"]


async def test_generation_failed(ctx):
    job_id = await ctx.create_job()
    await ctx.spec_ready(job_id)
    await ctx.client.post(f"/jobs/{job_id}/confirm", headers=ALICE)
    r = await ctx.routine_callback(
        job_id, mode="build", attempt=0, status="failed", reason="tests failed", log_tail="E..."
    )
    assert r.status_code == 204
    job = await ctx.get_job(job_id)
    assert job["state"] == "failed"
    assert ctx.dispatcher.calls == []


async def test_build_passed(ctx):
    job_id = await ctx.create_job()
    await ctx.to_building(job_id)
    r = await ctx.build_callback(
        job_id=job_id,
        attempt=0,
        status="passed",
        run_url="https://github.com/x/automation-builds/actions/runs/1",
        artifact_key=f"jobs/{job_id}/attempt-0/App.zip",
        guide_key=f"jobs/{job_id}/attempt-0/Guide.pdf",
        report=None,
    )
    assert r.status_code == 204
    job = await ctx.get_job(job_id)
    assert job["state"] == "ready"
    assert job["run_url"].endswith("/runs/1")
    # Duplicate delivery is ignored.
    again = await ctx.build_callback(job_id=job_id, attempt=0, status="failed")
    assert again.status_code == 204
    assert (await ctx.get_job(job_id))["state"] == "ready"


async def test_build_callback_needs_a_valid_signature(ctx):
    job_id = await ctx.create_job()
    await ctx.to_building(job_id)
    r = await ctx.build_callback(signature="sha256=bad", job_id=job_id, attempt=0, status="passed")
    assert r.status_code == 401
    r = await ctx.client.post("/internal/build-callback", json={"job_id": job_id})
    assert r.status_code == 401
    assert (await ctx.get_job(job_id))["state"] == "building"


async def test_build_callback_for_a_future_attempt_is_rejected(ctx):
    job_id = await ctx.create_job()
    await ctx.to_building(job_id)
    r = await ctx.build_callback(job_id=job_id, attempt=1, status="passed")
    assert r.status_code == 409


async def test_failed_builds_are_repaired_twice_then_fail(ctx):
    job_id = await ctx.create_job()
    await ctx.to_building(job_id)
    report = {
        "stage": "smoke_test",
        "command": "app.exe --smoke-test",
        "test": "t",
        "log_tail": "E",
    }

    for attempt in (1, 2):
        r = await ctx.build_callback(
            job_id=job_id, attempt=attempt - 1, status="failed", report=report
        )
        assert r.status_code == 204
        job = await ctx.get_job(job_id)
        assert (job["state"], job["attempt"]) == ("repairing", attempt)
        mode, fired, data = ctx.provider.calls[-1]
        assert (mode, fired.attempt, fired.branch) == ("repair", attempt, f"claude/job-{job_id}")
        assert data["report"]["stage"] == "smoke_test"

        await ctx.generated(job_id, attempt=attempt, mode="repair")
        assert (await ctx.get_job(job_id))["state"] == "building"
        assert ctx.dispatcher.calls[-1] == (job_id, f"claude/job-{job_id}", attempt)

    r = await ctx.build_callback(job_id=job_id, attempt=2, status="failed", report=report)
    assert r.status_code == 204
    job = await ctx.get_job(job_id)
    assert job["state"] == "failed"
    assert "repair" in job["failure_reason"]
    modes = [(a["mode"], a["attempt"]) for a in job["attempts"]]
    assert modes == [("spec", 0), ("build", 0), ("repair", 1), ("repair", 2)]


# --- fire failures ----------------------------------------------------------------------


async def test_rate_limited_fire_is_retried_later(ctx):
    ctx.provider.fail_next = [RetryLater(120, "rate limited (429)")]
    job_id = await ctx.create_job()
    job = await ctx.get_job(job_id)
    assert job["state"] == "spec_requested"
    assert [a["status"] for a in job["attempts"]] == ["rate_limited"]

    async with ctx.session() as session:
        assert await ctx.jobs.retry_pending(session) == 0  # too early
    ctx.clock.advance(seconds=121)
    async with ctx.session() as session:
        assert await ctx.jobs.retry_pending(session) == 1

    job = await ctx.get_job(job_id)
    assert [a["status"] for a in job["attempts"]] == ["rate_limited", "open"]
    await ctx.spec_ready(job_id)
    assert (await ctx.get_job(job_id))["state"] == "spec_ready"


async def test_rate_limited_build_stays_queued(ctx):
    job_id = await ctx.create_job()
    await ctx.spec_ready(job_id)
    ctx.provider.fail_next = [RetryLater(60, "429")]
    r = await ctx.client.post(f"/jobs/{job_id}/confirm", headers=ALICE)
    assert r.json()["state"] == "queued"
    ctx.clock.advance(seconds=61)
    async with ctx.session() as session:
        await ctx.jobs.retry_pending(session)
    assert (await ctx.get_job(job_id))["state"] == "generating"


async def test_unknown_fire_is_never_refired_but_accepts_a_late_callback(ctx):
    ctx.provider.fail_next = [FireUnknown("read timeout")]
    job_id = await ctx.create_job()
    job = await ctx.get_job(job_id)
    assert [a["status"] for a in job["attempts"]] == ["unknown"]
    ctx.clock.advance(minutes=5)
    async with ctx.session() as session:
        assert await ctx.jobs.retry_pending(session) == 0
    assert len(ctx.provider.calls) == 0
    await ctx.spec_ready(job_id)
    assert (await ctx.get_job(job_id))["state"] == "spec_ready"


async def test_rejected_fire_fails_the_job(ctx):
    ctx.provider.fail_next = [FireRejected("fire endpoint returned 401")]
    job_id = await ctx.create_job()
    job = await ctx.get_job(job_id)
    assert job["state"] == "failed"
    assert "401" in job["failure_reason"]


# --- watchdog ---------------------------------------------------------------------------


async def run_watchdog(ctx):
    async with ctx.session() as session:
        return await ctx.jobs.run_watchdog(session)


async def test_watchdog_fails_a_spec_without_callback(ctx):
    job_id = await ctx.create_job()
    ctx.clock.advance(minutes=14)
    await run_watchdog(ctx)
    assert (await ctx.get_job(job_id))["state"] == "spec_requested"
    ctx.clock.advance(minutes=2)
    await run_watchdog(ctx)
    job = await ctx.get_job(job_id)
    assert job["state"] == "failed"
    assert "15 minutes" in job["failure_reason"]
    # The session link is kept for debugging.
    assert job["attempts"][0]["status"] == "timed_out"
    assert job["attempts"][0]["session_url"]
    # A callback that arrives after the timeout is ignored.
    late = await ctx.routine_callback(job_id, mode="spec", revision=0, status="ok")
    assert late.status_code == 204
    assert (await ctx.get_job(job_id))["state"] == "failed"


async def test_watchdog_fails_generation_and_build_timeouts(ctx):
    generating = await ctx.create_job()
    await ctx.spec_ready(generating)
    await ctx.client.post(f"/jobs/{generating}/confirm", headers=ALICE)
    building = await ctx.create_job()
    await ctx.to_building(building)

    ctx.clock.advance(minutes=31)
    await run_watchdog(ctx)
    assert (await ctx.get_job(generating))["state"] == "failed"
    assert (await ctx.get_job(building))["state"] == "building"
    ctx.clock.advance(minutes=15)
    await run_watchdog(ctx)
    assert (await ctx.get_job(building))["state"] == "failed"


async def test_watchdog_expires_unconfirmed_specs_and_drops_descriptions(ctx):
    job_id = await ctx.create_job()
    await ctx.spec_ready(job_id)
    ctx.clock.advance(days=31)
    await run_watchdog(ctx)
    job = await ctx.get_job(job_id)
    assert job["state"] == "expired"
    assert job["description"] is None
    assert job["spec"] is not None  # specs are kept
