import json

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from engine.guards import unblock_network
from engine.loader import load_spec
from engine.ui.fields import check_scalar, display_text, make_field
from engine.ui.guide import render_guide
from engine.ui.window import MainWindow
from spec.models import AutomationSpec


@pytest.fixture
def window(qapp, invoice, store, tmp_path):
    w = MainWindow(
        invoice,
        store,
        inputs=invoice.sample_inputs(),
        output_dir=tmp_path / "out",
        open_results=False,
    )
    w.show()
    yield w
    w.close()


def test_first_start_asks_for_settings(window, store):
    assert window.stack.currentWidget() is window.setup_page
    assert not window._save_settings()  # business name is required
    assert window.settings_form.errors["business_name"].text() == "Required"
    window.settings_form.widgets["business_name"].set_value("My Shop")
    assert window._save_settings()
    assert store.load_settings()["business_name"] == "My Shop"
    assert window.stack.currentWidget() is window.run_page


def test_run_shows_result_and_writes_the_pdf(window, store, tmp_path):
    store.save_settings({"business_name": "My Shop"})
    result = window.run()
    assert result is not None
    assert (tmp_path / "out" / "INV-1.pdf").is_file()
    assert window.stack.currentWidget() is window.result_page


def test_run_without_settings_goes_to_setup(window):
    assert window.run() is None
    assert window.stack.currentWidget() is window.setup_page


def test_validation_blocks_the_run(window, store, tmp_path):
    store.save_settings({"business_name": "My Shop"})
    form = window.inputs_form
    form.widgets["customer_name"].set_value("")
    form.widgets["items"].set_value([{"description": "a", "qty": "two", "rate": "5"}])
    assert window.run() is None
    assert form.errors["customer_name"].text() == "Required"
    assert form.errors["items"].text() == "Row 1, Qty: enter a number"
    assert not window.banner.isHidden()
    assert not (tmp_path / "out").exists()
    form.widgets["customer_name"].set_value("Fixed")  # typing clears the error
    assert form.errors["customer_name"].isHidden()


def test_failure_shows_safe_error_screen(window, store, tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    store.save_settings({"business_name": "My Shop", "output_folder": str(blocker)})
    window.inputs_form.widgets["customer_name"].set_value("Private Name 123")
    assert window.run() is None
    assert window.stack.currentWidget() is window.result_page
    from PySide6.QtWidgets import QPushButton

    buttons = {b.text(): b for b in window.result_page.findChildren(QPushButton)}
    from PySide6.QtWidgets import QLabel

    texts = " ".join(label.text() for label in window.result_page.findChildren(QLabel))
    assert "Couldn't save to the output folder." in texts
    assert "file.save" not in texts  # step names stay in the report
    buttons["Copy error report"].click()
    report = QApplication.clipboard().text()
    assert "file.save" in report and "Private Name 123" not in report


def test_table_widget_round_trip(qapp, invoice):
    items = next(f for f in invoice.spec.inputs if f.key == "items")
    widget = make_field(items)
    widget.set_value([{"description": "x", "qty": 2, "rate": 1.5}])
    assert widget.value() == [{"description": "x", "qty": "2", "rate": "1.5"}]
    widget.set_value([])
    assert widget.value() == [
        {"description": "", "qty": "", "rate": ""}
    ]  # one empty row to type in
    widget.table.selectRow(0)
    widget._remove_row()
    assert widget.value() == []


SPEC_ALL_TYPES = {
    "id": "all-types",
    "version": "1.0.0",
    "title": "All types",
    "category": "other",
    "inputs": [
        {"key": "t", "type": "text", "label": "T", "multiline": True},
        {"key": "n", "type": "number", "label": "N", "min": 1, "max": 5},
        {"key": "m", "type": "money", "label": "M", "currency": "USD"},
        {"key": "p", "type": "phone", "label": "P"},
        {"key": "e", "type": "email", "label": "E"},
        {"key": "d", "type": "date", "label": "D"},
        {"key": "f", "type": "file", "label": "F", "extensions": ["pdf"]},
        {"key": "fs", "type": "files", "label": "FS", "min_count": 2},
        {"key": "fo", "type": "folder", "label": "FO"},
        {"key": "i", "type": "image_file", "label": "I"},
        {"key": "s", "type": "select", "label": "S", "options": ["a", "b"]},
        {"key": "c", "type": "checkbox", "label": "C"},
        {
            "key": "tb",
            "type": "table",
            "label": "TB",
            "columns": [
                {"key": "x", "type": "text"},
                {"key": "y", "type": "checkbox"},
                {"key": "z", "type": "select", "options": ["u", "v"]},
            ],
        },
    ],
    "steps": [{"block": "custom.step", "args": {"description": "d"}}],
    "output": {"type": "none"},
}


def test_every_field_type_round_trips(qapp):
    spec = AutomationSpec.model_validate(SPEC_ALL_TYPES)
    values = {
        "t": "line 1\nline 2",
        "n": "3",
        "m": "9.99",
        "p": "+91 00000 00000",
        "e": "a@example.com",
        "d": "2026-10-17",
        "f": "/tmp/a.pdf",
        "fs": ["/tmp/a.pdf", "/tmp/b.pdf"],
        "fo": "/tmp",
        "i": "/tmp/logo.png",
        "s": "b",
        "c": True,
        "tb": [{"x": "row", "y": True, "z": "v"}],
    }
    for field in spec.inputs:
        widget = make_field(field)
        widget.set_value(values[field.key])
        assert widget.value() == values[field.key], field.type
        assert widget.validate() is None, field.type


def test_field_checks(qapp):
    spec = AutomationSpec.model_validate(SPEC_ALL_TYPES)
    by_key = {f.key: f for f in spec.inputs}
    assert check_scalar(by_key["n"], "9") == "Must be at most 5"
    assert check_scalar(by_key["n"], "0") == "Must be at least 1"
    assert check_scalar(by_key["n"], "x") == "Enter a number"
    assert check_scalar(by_key["e"], "not-an-email").startswith("Enter an email")
    assert check_scalar(by_key["p"], "12") == "Enter a phone number"
    files = make_field(by_key["fs"])
    files.set_value(["/tmp/one.pdf"])
    assert files.validate() == "Choose at least 2 files"
    assert display_text(18.0) == "18" and display_text(1.5) == "1.5" and display_text(None) == ""


def test_select_and_checkbox_cells(qapp):
    spec = AutomationSpec.model_validate(SPEC_ALL_TYPES)
    table = make_field(spec.inputs[-1])
    table.set_value([{"x": "a", "y": False, "z": ""}])
    table.table.item(0, 1).setCheckState(Qt.CheckState.Checked)
    assert table.value() == [{"x": "a", "y": True, "z": ""}]


def test_guide_mode_renders_every_screen(qapp, invoice, tmp_path):
    screens = render_guide(invoice, tmp_path / "guide")
    names = [s["file"] for s in screens]
    assert names == ["01-setup.png", "02-fill-in.png", "03-result.png", "04-check-fields.png"]
    for name in names:
        assert (tmp_path / "guide" / name).stat().st_size > 5000
    manifest = json.loads((tmp_path / "guide" / "manifest.json").read_text())
    assert manifest["automation"] == "invoice-generator"
    assert (tmp_path / "guide" / "sample-output.pdf").is_file()


def test_guide_mode_leaves_no_data_behind(qapp, invoice, tmp_path, monkeypatch):
    monkeypatch.setenv("MAKEMYEXE_DATA_DIR", str(tmp_path / "real-data"))
    render_guide(invoice, tmp_path / "guide")
    assert not (tmp_path / "real-data").exists()


@pytest.fixture(autouse=True)
def _network():
    yield
    unblock_network()


def test_spec_without_settings_starts_on_the_form(qapp, tmp_path):
    from tests.engine.test_blocks import merge_spec

    loaded = merge_spec(tmp_path)
    from engine.storage import Store

    w = MainWindow(loaded, Store(loaded.spec.id, root=tmp_path / "d"), open_results=False)
    assert w.stack.currentWidget() is w.run_page
    assert not hasattr(w, "settings_button")
    assert load_spec(loaded.dir / "spec.json").spec.id == "pdf-merge-test"


def test_rename_preview_apply_and_undo_in_the_window(qapp, tmp_path):
    from PySide6.QtWidgets import QPushButton, QTableWidget

    from engine.storage import Store
    from tests.conftest import AUTOMATIONS_DIR

    loaded = load_spec(AUTOMATIONS_DIR / "bulk-rename" / "spec.json")
    inputs = loaded.sample_inputs(tmp_path / "ws")
    folder = tmp_path / "ws" / "Holiday photos"
    before = sorted(p.name for p in folder.iterdir())
    w = MainWindow(
        loaded, Store(loaded.spec.id, root=tmp_path / "d"), inputs=inputs, open_results=False
    )

    assert w.run() is not None
    assert sorted(p.name for p in folder.iterdir()) == before  # preview only
    table = w.result_page.findChild(QTableWidget, "previewTable")
    assert table.rowCount() == len(before)
    assert table.item(0, 1).text() == "Goa trip 001.jpg"
    buttons = {b.text(): b for b in w.result_page.findChildren(QPushButton)}
    buttons["Cancel"].click()
    assert w.stack.currentWidget() is w.run_page
    assert sorted(p.name for p in folder.iterdir()) == before

    w.run()
    {b.text(): b for b in w.result_page.findChildren(QPushButton)}["Rename 5 files"].click()
    assert sorted(p.name for p in folder.iterdir())[0] == "Goa trip 001.jpg"
    {b.text(): b for b in w.result_page.findChildren(QPushButton)}["Undo"].click()
    assert sorted(p.name for p in folder.iterdir()) == before


def test_files_field_shows_names_but_keeps_paths(qapp):
    spec = AutomationSpec.model_validate(SPEC_ALL_TYPES)
    widget = make_field(next(f for f in spec.inputs if f.key == "fs"))
    widget.set_value(["/very/long/path/to/a.pdf", "/x/b.pdf"])
    assert [widget.list.item(i).text() for i in range(2)] == ["a.pdf", "b.pdf"]
    assert widget.value() == ["/very/long/path/to/a.pdf", "/x/b.pdf"]


def test_guide_mode_for_renames_never_touches_the_samples(qapp, tmp_path):
    from tests.conftest import AUTOMATIONS_DIR

    samples = AUTOMATIONS_DIR / "bulk-rename" / "samples" / "Holiday photos"
    before = sorted(p.name for p in samples.iterdir())
    screens = render_guide(load_spec(AUTOMATIONS_DIR / "bulk-rename" / "spec.json"), tmp_path / "g")
    assert [s["file"] for s in screens] == [
        "01-fill-in.png",
        "02-preview.png",
        "03-result.png",
        "04-undone.png",
        "05-check-fields.png",
    ]
    assert sorted(p.name for p in samples.iterdir()) == before
