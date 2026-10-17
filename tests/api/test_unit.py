import json

import httpx
import pytest

from api.dispatch import DispatchError, GitHubDispatcher
from api.ids import new_job_id
from api.providers import FireRejected, FireUnknown, JobContext, RetryLater
from api.providers.routine import RoutineProvider
from api.security import callback_token, sign_body, verify_callback_token, verify_signature
from api.states import TERMINAL, TRANSITIONS, InvalidTransition, JobState, check_transition

pytestmark = pytest.mark.anyio

JOB = JobContext(
    job_id="job_01J00000000000000000000000",
    revision=1,
    attempt=0,
    callback_url="https://api.test/internal/routine-callback",
    callback_token="tok",
    branch="claude/job-job_01J00000000000000000000000",
)


def test_job_ids_are_sortable_and_unique():
    ids = [new_job_id() for _ in range(50)]
    assert len(set(ids)) == 50
    assert all(i.startswith("job_") and len(i) == 30 for i in ids)


def test_state_machine():
    check_transition(JobState.SPEC_READY, JobState.QUEUED)
    with pytest.raises(InvalidTransition):
        check_transition(JobState.SPEC_REQUESTED, JobState.BUILDING)
    for state in TERMINAL:
        assert TRANSITIONS[state] == frozenset()
    assert set(TRANSITIONS) == set(JobState)


def test_callback_tokens_and_signatures():
    token = callback_token("secret", "job_a")
    assert verify_callback_token("secret", "job_a", token)
    assert not verify_callback_token("secret", "job_b", token)
    assert not verify_callback_token("other", "job_a", token)
    sig = sign_body("s", b"{}")
    assert verify_signature("s", b"{}", sig)
    assert not verify_signature("s", b"{ }", sig)
    assert not verify_signature("s", b"{}", None)


def provider(handler) -> RoutineProvider:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return RoutineProvider(
        spec_url="https://fire.test/spec",
        spec_token="spec-tok",
        build_url="https://fire.test/build",
        build_token="build-tok",
        client=client,
    )


async def test_routine_fire_payloads():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "type": "routine_fire",
                "claude_code_session_id": "session_1",
                "claude_code_session_url": "https://claude.ai/code/session_1",
            },
        )

    p = provider(handler)
    ref = await p.request_spec(JOB, "desc", [{"question": "q", "answer": "a"}], {"id": "x"})
    assert (ref.session_id, ref.session_url) == ("session_1", "https://claude.ai/code/session_1")
    await p.request_build(JOB, {"id": "x"})
    await p.request_repair(JOB, {"stage": "build"})

    spec_req, build_req, repair_req = seen
    assert str(spec_req.url) == "https://fire.test/spec"
    assert spec_req.headers["Authorization"] == "Bearer spec-tok"
    assert spec_req.headers["anthropic-version"] == "2023-06-01"
    payload = json.loads(json.loads(spec_req.content)["text"])
    assert payload == {
        "v": 1,
        "mode": "spec",
        "job_id": JOB.job_id,
        "revision": 1,
        "callback_url": JOB.callback_url,
        "callback_token": "tok",
        "description": "desc",
        "previous_spec": {"id": "x"},
        "answers": [{"question": "q", "answer": "a"}],
    }
    assert build_req.headers["Authorization"] == "Bearer build-tok"
    assert json.loads(json.loads(build_req.content)["text"])["mode"] == "build"
    repair = json.loads(json.loads(repair_req.content)["text"])
    assert (repair["mode"], repair["branch"], repair["report"]) == (
        "repair",
        JOB.branch,
        {"stage": "build"},
    )


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (httpx.Response(429, headers={"Retry-After": "90"}), RetryLater),
        (httpx.Response(500), FireUnknown),
        (httpx.Response(502), FireUnknown),
        (httpx.Response(401, text="bad token"), FireRejected),
        (httpx.Response(200, text="not json"), FireUnknown),
    ],
)
async def test_routine_fire_errors(response, error):
    with pytest.raises(error) as exc:
        await provider(lambda _: response).request_build(JOB, {})
    if error is RetryLater:
        assert exc.value.retry_after_s == 90


async def test_routine_fire_transport_errors():
    def connect_error(request):
        raise httpx.ConnectError("refused", request=request)

    def read_timeout(request):
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(RetryLater):
        await provider(connect_error).request_build(JOB, {})
    with pytest.raises(FireUnknown):
        await provider(read_timeout).request_build(JOB, {})


async def test_routine_fire_refuses_oversized_payload_and_missing_config():
    p = provider(lambda _: httpx.Response(200))
    with pytest.raises(FireRejected, match="limit"):
        await p.request_build(JOB, {"blob": "x" * 70_000})
    unconfigured = RoutineProvider(spec_url="", spec_token="", build_url="", build_token="")
    with pytest.raises(FireRejected, match="not configured"):
        await unconfigured.request_spec(JOB, "d", [], None)


async def test_github_dispatch():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(204)

    d = GitHubDispatcher(
        token="gh",
        repo="o/automation-builds",
        workflow="build.yml",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    await d.dispatch("job_1", "claude/job-job_1", 1)
    (req,) = seen
    assert str(req.url) == (
        "https://api.github.com/repos/o/automation-builds/actions/workflows/build.yml/dispatches"
    )
    assert json.loads(req.content) == {
        "ref": "main",
        "inputs": {"job_id": "job_1", "branch": "claude/job-job_1", "attempt": "1"},
    }

    failing = GitHubDispatcher(
        token="gh",
        repo="o/r",
        workflow="w.yml",
        client=httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(404))),
    )
    with pytest.raises(DispatchError):
        await failing.dispatch("job_1", "b", 0)
    with pytest.raises(DispatchError, match="not configured"):
        await GitHubDispatcher(token="", repo="o/r", workflow="w.yml").dispatch("j", "b", 0)


def test_routine_mode_refuses_dev_secrets(tmp_path):
    from pydantic import SecretStr

    from api.app import create_app
    from api.config import Settings

    base = {"_env_file": None, "database_url": f"sqlite+aiosqlite:///{tmp_path / 'x.db'}"}
    with pytest.raises(RuntimeError, match="CALLBACK_TOKEN_SECRET, BUILD_CALLBACK_SECRET"):
        create_app(Settings(**base, provider="routine"))
    strong = {
        "callback_token_secret": SecretStr("a" * 40),
        "build_callback_secret": SecretStr("b" * 40),
    }
    with pytest.raises(RuntimeError, match="DEV_AUTH must be false"):
        create_app(Settings(**base, provider="routine", dev_auth=True, **strong))
    create_app(Settings(**base, provider="routine", **strong))
