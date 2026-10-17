import os
from datetime import date
from pathlib import Path

import pytest

from engine.context import RunContext
from engine.loader import LoadedSpec, load_spec
from engine.storage import Store
from tests.conftest import INVOICE_SPEC

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def invoice() -> LoadedSpec:
    return load_spec(INVOICE_SPEC)


@pytest.fixture
def store(tmp_path) -> Store:
    return Store("invoice-generator", root=tmp_path / "data")


@pytest.fixture
def make_ctx(invoice, store, tmp_path):
    def make(inputs=None, settings=None, loaded=None, **kwargs) -> RunContext:
        loaded = loaded or invoice
        return RunContext(
            spec=loaded.spec,
            inputs=loaded.sample_inputs() if inputs is None else inputs,
            settings=loaded.sample_settings() if settings is None else settings,
            store=kwargs.pop("store", store),
            output_dir=kwargs.pop("output_dir", tmp_path / "out"),
            spec_dir=loaded.dir,
            today=date(2026, 10, 17),
            **kwargs,
        )

    return make


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    from engine.ui.theme import apply_theme

    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    return app


@pytest.fixture(autouse=True)
def _delete_widgets(request):
    """Delete every top-level widget a test made while QApplication is still alive.

    Otherwise Python may destroy them at interpreter exit after QApplication, which crashes Qt.
    """
    yield
    if "qapp" not in request.fixturenames:
        return
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication

    for widget in QApplication.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QApplication.processEvents()


def write_pdf(path: Path, pages: int, text: str = "page") -> Path:
    from fpdf import FPDF

    pdf = FPDF()
    for n in range(pages):
        pdf.add_page()
        pdf.set_font("Helvetica", size=12)
        pdf.cell(40, 10, f"{text} {n + 1}")
    pdf.output(str(path))
    return path
