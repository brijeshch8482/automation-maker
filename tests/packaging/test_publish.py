"""build.publish (Job 2): trusts nothing in the artifact, uploads, signs and retries."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import ClassVar

import pytest

from build import publish
from build.publish import PublishError

SETTINGS = {
    "API_BASE_URL": "https://api.test",
    "BUILD_CALLBACK_SECRET": "s3cret",
    "R2_ACCOUNT_ID": "acct",
    "R2_ACCESS_KEY_ID": "key",
    "R2_SECRET_ACCESS_KEY": "secret",
    "R2_BUCKET": "builds",
}


def artifact(tmp_path, report=None, files=("MakePDF.zip", "Guide.pdf")):
    folder = tmp_path / "artifact"
    folder.mkdir()
    if report is not None:
        (folder / "report.json").write_text(json.dumps(report))
    for name in files:
        (folder / name).write_bytes(b"data")
    return folder


@pytest.fixture
def sent(monkeypatch):
    calls = {"uploads": [], "callbacks": []}
    monkeypatch.setattr(publish, "upload", lambda path, key, env: calls["uploads"].append(key))
    monkeypatch.setattr(
        publish,
        "send_callback",
        lambda url, secret, payload: calls["callbacks"].append(payload) or 204,
    )
    return calls


def test_passed_build_is_uploaded_and_reported(tmp_path, sent):
    folder = artifact(tmp_path, {"status": "passed", "exe": "MakePDF"})
    payload = publish.publish(folder, "job_1", 0, "https://run", "success", SETTINGS)
    assert payload["status"] == "passed"
    assert sent["uploads"] == ["jobs/job_1/attempt-0/MakePDF.zip", "jobs/job_1/attempt-0/Guide.pdf"]
    assert sent["callbacks"] == [payload]
    assert payload["report"] is None


def test_report_alone_cannot_claim_a_pass(tmp_path, sent):
    # Job 1 ran generated code, which could write any report.json: its job result decides too.
    folder = artifact(tmp_path, {"status": "passed", "exe": "MakePDF"})
    payload = publish.publish(folder, "job_1", 1, "https://run", "failure", SETTINGS)
    assert payload["status"] == "failed"
    assert sent["uploads"] == []
    assert payload["report"]["stage"] == "build"


def test_failed_build_sends_the_report_cut_to_size(tmp_path, sent):
    report = {
        "status": "failed",
        "stage": "smoke_test",
        "command": "MakePDF.exe --smoke-test",
        "test": None,
        "log_tail": "x" * 50_000,
        "extra": "ignored",
    }
    payload = publish.publish(artifact(tmp_path, report), "job_1", 0, "u", "failure", SETTINGS)
    assert payload["status"] == "failed"
    assert set(payload["report"]) == {"stage", "command", "test", "log_tail"}
    assert payload["report"]["stage"] == "smoke_test"
    assert len(payload["report"]["log_tail"]) == 8000


def test_missing_report(tmp_path, sent):
    payload = publish.publish(artifact(tmp_path, None, ()), "job_1", 0, "u", "cancelled", SETTINGS)
    assert payload["report"]["stage"] == "build"
    assert "cancelled" in payload["report"]["log_tail"]


@pytest.mark.parametrize(
    ("report", "files", "message"),
    [
        ({"status": "passed", "exe": "../../etc"}, (), "no valid app name"),
        ({"status": "passed", "exe": "MakePDF"}, ("Guide.pdf",), "MakePDF.zip is missing"),
    ],
)
def test_untrusted_artifact_is_checked(tmp_path, sent, report, files, message):
    with pytest.raises(PublishError, match=message):
        publish.publish(artifact(tmp_path, report, files), "job_1", 0, "u", "success", SETTINGS)
    assert sent["callbacks"] == []


def test_invalid_job_id(tmp_path, sent):
    with pytest.raises(PublishError, match="invalid job id"):
        publish.publish(artifact(tmp_path, {}), "../x", 0, "u", "success", SETTINGS)


def test_not_configured_only_checks(tmp_path, sent, capsys):
    folder = artifact(tmp_path, {"status": "passed", "exe": "MakePDF"})
    payload = publish.publish(folder, "job_1", 0, "u", "success", dict.fromkeys(SETTINGS, ""))
    assert payload["status"] == "passed"
    assert sent == {"uploads": [], "callbacks": []}
    assert "not configured" in capsys.readouterr().out


def test_partly_configured_is_an_error(tmp_path, sent):
    env = {**SETTINGS, "R2_BUCKET": ""}
    with pytest.raises(PublishError, match="missing: R2_BUCKET"):
        publish.publish(artifact(tmp_path, {}), "job_1", 0, "u", "success", env)


class _Api(BaseHTTPRequestHandler):
    statuses: ClassVar[list[int]] = []
    received: ClassVar[list[tuple[bytes, str]]] = []

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        _Api.received.append((body, self.headers["X-Signature"]))
        self.send_response(_Api.statuses.pop(0))
        self.end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture
def api():
    server = HTTPServer(("127.0.0.1", 0), _Api)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _Api.received.clear()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def test_callback_retries_while_the_api_wakes_up(api, monkeypatch):
    monkeypatch.setattr(publish, "RETRY_SECONDS", 0)
    _Api.statuses = [502, 503, 204]
    assert publish.send_callback(api, "s3cret", {"job_id": "j"}) == 204
    assert len(_Api.received) == 3
    body, signature = _Api.received[-1]
    assert signature == publish.sign_body("s3cret", body)


def test_callback_for_a_closed_attempt_is_done_and_401_is_an_error(api, monkeypatch):
    monkeypatch.setattr(publish, "RETRY_SECONDS", 0)
    _Api.statuses = [409]
    assert publish.send_callback(api, "s", {}) == 409
    _Api.statuses = [401]
    with pytest.raises(PublishError, match="HTTP 401"):
        publish.send_callback(api, "s", {})
    assert len(_Api.received) == 2  # no retry on a client error


def test_main_exit_codes(tmp_path, monkeypatch, sent):
    for name in SETTINGS:
        monkeypatch.delenv(name, raising=False)
    folder = artifact(tmp_path, {"status": "passed", "exe": "MakePDF"})
    args = ["--artifact-dir", str(folder), "--attempt", "0", "--run-url", "u"]
    assert publish.main([*args, "--job-id", "job_1", "--build-result", "success"]) == 0
    assert publish.main([*args, "--job-id", "bad id", "--build-result", "success"]) == 1
