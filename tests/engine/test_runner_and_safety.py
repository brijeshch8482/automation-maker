import json
import socket

import pytest
from pypdf import PdfReader

from engine import __main__ as cli
from engine.errors import EngineError, StepError, error_report
from engine.guards import OfflineError, block_network, unblock_network
from engine.loader import load_spec
from engine.runner import run
from engine.smoke import smoke_test
from engine.storage import Store
from engine.values import SavedFile
from tests.conftest import AUTOMATIONS_DIR, INVOICE_SPEC


def test_invoice_end_to_end(make_ctx, store, tmp_path):
    first = run(make_ctx())
    second = run(make_ctx())
    assert isinstance(first.last_value, SavedFile)
    assert first.last_value.path.name == "INV-1.pdf"
    assert second.last_value.path.name == "INV-2.pdf"
    assert store.counter_value("invoice_no") == 2
    text = PdfReader(second.last_value.path).pages[0].extract_text()
    assert "INV-2" in text and "3,304.00" in text


def test_failed_run_does_not_advance_the_counter(make_ctx, store, tmp_path):
    blocker = tmp_path / "not-a-folder"
    blocker.write_text("x")
    ctx = make_ctx(settings={"business_name": "B", "output_folder": str(blocker)})
    with pytest.raises(StepError) as exc:
        run(ctx)
    assert exc.value.index == 3 and exc.value.block == "file.save"
    assert store.counter_value("invoice_no") is None
    assert run(make_ctx()).last_value.path.name == "INV-1.pdf"


def test_error_report_contains_no_user_data(make_ctx, invoice):
    secret = "Secret Customer 98765"
    inputs = {
        **invoice.sample_inputs(),
        "customer_name": secret,
        "items": [{"description": secret, "qty": "x", "rate": "1"}],
    }
    with pytest.raises(StepError) as exc:
        run(make_ctx(inputs=inputs))
    report = error_report(exc.value, "invoice-generator", "1.0.0")
    assert "step: 2 (calc.line_totals)" in report
    assert "row 1: qty is not a number" in report
    assert secret not in report and "98765" not in report


def test_unexpected_errors_report_type_only(make_ctx):
    err = StepError(0, "x.y", ValueError("contains /home/user/private.pdf"))
    report = error_report(err, "a", "1")
    assert "error: ValueError" in report
    assert "private.pdf" not in report
    assert str(err) == "Step 1 (x.y): the step failed unexpectedly"


def test_offline_guard_blocks_connections():
    block_network()
    try:
        with pytest.raises(OfflineError):
            socket.create_connection(("example.com", 80))
        with pytest.raises(OfflineError):
            socket.getaddrinfo("example.com", 80)
        s = socket.socket()
        with pytest.raises(OfflineError):
            s.connect(("127.0.0.1", 9))
        s.close()
    finally:
        unblock_network()
    assert socket.getaddrinfo("127.0.0.1", 80)


def test_settings_storage(tmp_path):
    store = Store("x", root=tmp_path)
    assert store.load_settings() == {}
    store.save_settings({"business_name": "B"})
    assert Store("x", root=tmp_path).load_settings() == {"business_name": "B"}
    (tmp_path / "x" / "settings.json").write_text("{broken")
    assert store.load_settings() == {}


def test_bad_spec_is_reported_without_crashing(tmp_path):
    path = tmp_path / "spec.json"
    path.write_text(json.dumps({"id": "x"}))
    with pytest.raises(EngineError, match="not valid"):
        load_spec(path)
    with pytest.raises(EngineError, match="could not be read"):
        load_spec(tmp_path / "missing.json")


@pytest.mark.parametrize(
    "spec_path", sorted(AUTOMATIONS_DIR.glob("*/spec.json")), ids=lambda p: p.parent.name
)
def test_every_catalog_automation_runs_on_its_sample_data(spec_path):
    report = smoke_test(load_spec(spec_path))
    assert report["status"] == "passed", report.get("report")


@pytest.fixture
def restore_network():
    yield
    unblock_network()


def test_cli_smoke_test(capsys, restore_network):
    assert cli.main([str(INVOICE_SPEC), "--smoke-test"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "passed"
    assert report["output"]["file"] == "INV-1.pdf"


def test_cli_bad_spec(tmp_path, capsys, restore_network):
    bad = tmp_path / "spec.json"
    bad.write_text("{}")
    assert cli.main([str(bad), "--smoke-test"]) == 2
    assert "not valid" in capsys.readouterr().err


def test_step_errors_keep_engine_messages():
    err = StepError(1, "calc.line_totals", EngineError("row 1: qty is empty"))
    assert str(err) == "Step 2 (calc.line_totals): row 1: qty is empty"
