"""The app window: header -> first-time setup -> inputs form -> run -> result."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFont, QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from engine.changes import UndoResult, apply_plan, undo
from engine.context import RunContext
from engine.errors import EngineError, StepError, error_report
from engine.fieldvalues import initial_values
from engine.loader import LoadedSpec
from engine.runner import RunResult, run
from engine.storage import Store, default_output_dir
from engine.ui.fields import FieldWidget, field_label, make_field
from engine.values import RenamePlan, SavedFile
from spec.models import SpecField

WINDOW_SIZE = (760, 720)


class FieldForm(QWidget):
    """Labels, controls, help and inline errors for a list of fields."""

    def __init__(self, fields: list[SpecField], values: dict[str, Any]) -> None:
        super().__init__()
        self.widgets: dict[str, FieldWidget] = {}
        self.errors: dict[str, QLabel] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        for field in fields:
            box = QVBoxLayout()
            box.setSpacing(4)
            widget = make_field(field)
            widget.set_value(values.get(field.key))
            if field.type != "checkbox":
                label = QLabel(
                    field_label(field)
                    + (' <span style="color:#be123c">*</span>' if field.required else "")
                )
                label.setObjectName("fieldLabel")
                label.setTextFormat(Qt.TextFormat.RichText)
                box.addWidget(label)
            box.addWidget(widget)
            if field.help:
                help_ = QLabel(field.help)
                help_.setObjectName("help")
                help_.setWordWrap(True)
                box.addWidget(help_)
            error = QLabel()
            error.setObjectName("fieldError")
            error.hide()
            box.addWidget(error)
            layout.addLayout(box)
            self.widgets[field.key] = widget
            self.errors[field.key] = error
            widget.changed.connect(lambda key=field.key: self._clear(key))

    def _clear(self, key: str) -> None:
        if not self.errors[key].isHidden():
            self.errors[key].hide()
            self.widgets[key].set_invalid(False)

    def values(self) -> dict[str, Any]:
        return {key: widget.value() for key, widget in self.widgets.items()}

    def validate(self) -> bool:
        ok = True
        for key, widget in self.widgets.items():
            problem = widget.validate()
            self.errors[key].setText(problem or "")
            self.errors[key].setVisible(bool(problem))
            widget.set_invalid(bool(problem))
            ok = ok and not problem
        return ok


def _card(*widgets: QWidget) -> QFrame:
    card = QFrame()
    card.setObjectName("card")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(20, 18, 20, 18)
    layout.setSpacing(12)
    for widget in widgets:
        layout.addWidget(widget)
    return card


def _scroll_page(*widgets: QWidget, footer: QWidget | None = None) -> QWidget:
    page = QWidget()
    page.setObjectName("page")
    outer = QVBoxLayout(page)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(0)
    inner = QWidget()
    inner.setObjectName("page")
    layout = QVBoxLayout(inner)
    layout.setContentsMargins(24, 20, 24, 20)
    layout.setSpacing(14)
    for widget in widgets:
        layout.addWidget(widget)
    layout.addStretch()
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setWidget(inner)
    outer.addWidget(scroll, 1)
    if footer:
        outer.addWidget(footer)
    return page


def _footer(*buttons: QWidget, note: QWidget | None = None) -> QWidget:
    bar = QWidget()
    bar.setObjectName("header")
    layout = QHBoxLayout(bar)
    layout.setContentsMargins(24, 12, 24, 12)
    if note:
        layout.addWidget(note)
    layout.addStretch()
    for button in buttons:
        layout.addWidget(button)
    return bar


def _button(text: str, slot: Callable[[], None], primary: bool = False) -> QPushButton:
    button = QPushButton(text)
    if primary:
        button.setObjectName("primary")
    button.clicked.connect(slot)
    return button


class MainWindow(QMainWindow):
    def __init__(
        self,
        loaded: LoadedSpec,
        store: Store,
        *,
        inputs: dict[str, Any] | None = None,
        output_dir: Path | None = None,
        open_results: bool = True,
    ) -> None:
        super().__init__()
        self.loaded = loaded
        self.spec = loaded.spec
        self.store = store
        self.output_dir = output_dir or default_output_dir(self.spec.title)
        self.open_results = open_results
        self.last_result: RunResult | None = None
        self.last_error: BaseException | None = None
        self.pending_plan: RenamePlan | None = None
        self.last_batch: int | None = None

        self.setWindowTitle(self.spec.title)
        self.resize(*WINDOW_SIZE)

        saved = store.load_settings()
        self.settings_form = FieldForm(
            self.spec.settings, {**initial_values(self.spec.settings, {}), **saved}
        )
        start_inputs = inputs if inputs is not None else initial_values(self.spec.inputs, {})
        self.inputs_form = FieldForm(self.spec.inputs, start_inputs)

        self.stack = QStackedWidget()
        self.setup_page = self._build_setup_page()
        self.run_page = self._build_run_page()
        self.result_page = QWidget()
        for page in (self.setup_page, self.run_page):
            self.stack.addWidget(page)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_header())
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        needs_setup = any(f.required and not saved.get(f.key) for f in self.spec.settings)
        self.show_page(self.setup_page if needs_setup else self.run_page)

    # --- building ---

    def _build_header(self) -> QWidget:
        header = QWidget()
        header.setObjectName("header")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(24, 14, 24, 14)
        title = QLabel(self.spec.title)
        title.setObjectName("title")
        layout.addWidget(title)
        online = self.spec.network.required
        badge = QLabel("🌐 Uses internet" if online else "🔒 Works offline")
        badge.setObjectName("badgeOnline" if online else "badge")
        if online:
            badge.setToolTip("Connects only to: " + ", ".join(self.spec.network.domains))
        layout.addWidget(badge)
        layout.addStretch()
        if self.spec.settings:
            self.settings_button = _button("Settings", lambda: self.show_page(self.setup_page))
            layout.addWidget(self.settings_button)
        return header

    def _build_setup_page(self) -> QWidget:
        intro = QLabel(
            "Entered once and saved on this PC. You can change them any time from Settings."
        )
        intro.setObjectName("intro")
        intro.setWordWrap(True)
        save = _button("Save", self._save_settings, primary=True)
        return _scroll_page(intro, _card(self.settings_form), footer=_footer(save))

    def _build_run_page(self) -> QWidget:
        self.banner = QLabel("Please fix the highlighted fields.")
        self.banner.setObjectName("banner")
        self.banner.hide()
        content: list[QWidget] = [self.banner]
        if self.spec.inputs:
            content.append(_card(self.inputs_form))
        else:
            ready = QLabel("Nothing to fill in. Press Run to start.")
            ready.setObjectName("intro")
            content.append(ready)
        run_button = _button("Run", self.run, primary=True)
        return _scroll_page(*content, footer=_footer(run_button))

    # --- navigation ---

    def show_page(self, page: QWidget) -> None:
        self.stack.setCurrentWidget(page)

    def _replace_result_page(self, page: QWidget) -> None:
        self.stack.removeWidget(self.result_page)
        self.result_page.deleteLater()
        self.result_page = page
        self.stack.addWidget(page)
        self.show_page(page)

    # --- actions ---

    def _save_settings(self) -> bool:
        if not self.settings_form.validate():
            return False
        self.store.save_settings(self.settings_form.values())
        self.show_page(self.run_page)
        return True

    def run(self) -> RunResult | None:
        settings = {**self.store.load_settings()}
        if any(f.required and not settings.get(f.key) for f in self.spec.settings):
            self.show_page(self.setup_page)
            self.settings_form.validate()
            return None
        if not self.inputs_form.validate():
            self.banner.show()
            return None
        self.banner.hide()

        ctx = RunContext(
            spec=self.spec,
            inputs=self.inputs_form.values(),
            settings=settings,
            store=self.store,
            output_dir=self.output_dir,
            spec_dir=self.loaded.dir,
        )
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            result = run(ctx)
        except Exception as err:  # every failure gets the safe error screen
            self.last_error = err
            self._replace_result_page(self._build_error_page(err))
            return None
        finally:
            QApplication.restoreOverrideCursor()
        self.last_result = result
        self.last_error = None
        if result.pending:
            # Files would change: show what will happen and wait for the user (ARCHITECTURE §1.5).
            self.pending_plan = result.pending[0]
            self._replace_result_page(self._build_preview_page(self.pending_plan))
            return result
        self._replace_result_page(self._build_result_page(result))
        if (
            self.open_results
            and self.spec.output.open_after
            and isinstance(result.last_value, SavedFile)
        ):
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(result.last_value.path)))
        return result

    def _build_result_page(self, result: RunResult) -> QWidget:
        title = QLabel("Done")
        title.setObjectName("resultTitle")
        widgets: list[QWidget] = [title]
        buttons: list[QWidget] = []
        saved = result.last_value if isinstance(result.last_value, SavedFile) else None
        if saved:
            text = QLabel(
                f"Saved <b>{_escape(saved.path.name)}</b> in the "
                f"<b>{_escape(saved.path.parent.name)}</b> folder."
            )
            text.setTextFormat(Qt.TextFormat.RichText)
            text.setWordWrap(True)
            text.setToolTip(str(saved.path))
            widgets.append(text)
            buttons += [
                _button("Open folder", lambda: _open(saved.path.parent)),
                _button("Open file", lambda: _open(saved.path), primary=True),
            ]
        again = _button("Make another", lambda: self.show_page(self.run_page))
        return _scroll_page(_card(*widgets), footer=_footer(again, *buttons))

    # --- file changes: preview -> apply -> undo ---

    def _build_preview_page(self, plan: RenamePlan) -> QWidget:
        title = QLabel("Check the new names")
        title.setObjectName("previewTitle")
        count = len(plan.moves)
        if not count:
            text = QLabel("Nothing to rename: every file already has its new name.")
            text.setWordWrap(True)
            back = _button("Back", lambda: self.show_page(self.run_page), primary=True)
            return _scroll_page(_card(title, text), footer=_footer(back))

        files = "file" if count == 1 else "files"
        lines = [
            f"{count} {files} in the <b>{_escape(plan.folder.name)}</b> folder will be renamed. "
            "Nothing changes until you press Rename, and you can undo it afterwards."
        ]
        if plan.adjusted:
            lines.append(
                f"{_count(plan.adjusted, 'new name')} got a number like “(2)” because the name "
                "was taken."
            )
        if plan.unchanged:
            lines.append(f"{_count(plan.unchanged, 'file')} already named like that, left as is.")
        text = QLabel("<br>".join(lines))
        text.setTextFormat(Qt.TextFormat.RichText)
        text.setWordWrap(True)

        table = QTableWidget(count, 2)
        table.setObjectName("previewTable")
        table.setHorizontalHeaderLabels(["Now", "New name"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for row, move in enumerate(plan.moves):
            table.setItem(row, 0, QTableWidgetItem(move.source.name))
            new = QTableWidgetItem(move.target.name)
            new.setFont(_bold(new.font()))
            table.setItem(row, 1, new)
        table.setMinimumHeight(min(60 + 30 * count, 380))

        cancel = _button("Cancel", lambda: self.show_page(self.run_page))
        apply = _button(f"Rename {count} {files}", self.apply_changes, primary=True)
        return _scroll_page(_card(title, text, table), footer=_footer(cancel, apply))

    def apply_changes(self) -> int | None:
        plan = self.pending_plan
        if plan is None:
            return None
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            # The description goes to the local undo log; it names no files.
            batch = apply_plan(
                plan, self.store, f"{self.spec.title}: renamed {len(plan.moves)} files"
            )
        except Exception as err:  # every failure gets the safe error screen
            self.last_error = err
            self._replace_result_page(self._build_error_page(err))
            return None
        finally:
            QApplication.restoreOverrideCursor()
        self.pending_plan = None
        self.last_batch = batch
        self._replace_result_page(self._build_applied_page(plan, batch))
        return batch

    def _build_applied_page(self, plan: RenamePlan, batch: int) -> QWidget:
        title = QLabel("Done")
        title.setObjectName("resultTitle")
        count = len(plan.moves)
        text = QLabel(
            f"Renamed {count} {'file' if count == 1 else 'files'} in the "
            f"<b>{_escape(plan.folder.name)}</b> folder. Changed your mind? Undo puts the old "
            "names back."
        )
        text.setTextFormat(Qt.TextFormat.RichText)
        text.setWordWrap(True)
        text.setToolTip(str(plan.folder))
        again = _button("Rename more", lambda: self.show_page(self.run_page))
        undo_button = _button("Undo", lambda: self.undo_changes(batch, plan.folder))
        open_folder = _button("Open folder", lambda: _open(plan.folder), primary=True)
        return _scroll_page(_card(title, text), footer=_footer(again, undo_button, open_folder))

    def undo_changes(self, batch: int, folder: Path) -> UndoResult | None:
        try:
            result = undo(self.store, batch)
        except Exception as err:  # every failure gets the safe error screen
            self.last_error = err
            self._replace_result_page(self._build_error_page(err))
            return None
        title = QLabel("Undone")
        title.setObjectName("resultTitle")
        lines = [f"{_count(result.restored, 'file')} renamed back to the old names."]
        if result.skipped:
            lines.append(
                f"{_count(result.skipped, 'file')} left as is: moved or renamed "
                "since, or their old name is now used by another file."
            )
        text = QLabel(" ".join(lines))
        text.setWordWrap(True)
        back = _button("Back to the form", lambda: self.show_page(self.run_page))
        open_folder = _button("Open folder", lambda: _open(folder), primary=True)
        self._replace_result_page(
            _scroll_page(_card(title, text), footer=_footer(back, open_folder))
        )
        return result

    def _build_error_page(self, error: BaseException) -> QWidget:
        title = QLabel("Something went wrong")
        title.setObjectName("errorTitle")
        text = QLabel(f"{_user_message(error)}\n\nNothing was changed in your files.")
        text.setWordWrap(True)
        hint = QLabel(
            "If it keeps happening, copy the error report and send it to us. "
            "It doesn't include anything you typed or any file contents."
        )
        hint.setObjectName("intro")
        hint.setWordWrap(True)
        report = error_report(error, self.spec.id, self.spec.version)
        copy = _button("Copy error report", lambda: QGuiApplication.clipboard().setText(report))
        back = _button("Back", lambda: self.show_page(self.run_page), primary=True)
        return _scroll_page(_card(title, text, hint), footer=_footer(copy, back))


def _user_message(error: BaseException) -> str:
    """The plain message for the screen; the step name stays in the error report."""
    cause = error.cause if isinstance(error, StepError) else error
    if not isinstance(cause, EngineError):
        return "The automation stopped unexpectedly."
    message = str(cause)
    return message[:1].upper() + message[1:] + ("" if message.endswith(".") else ".")


def _open(path: Path) -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" + ("" if n == 1 else "s")


def _bold(font: QFont) -> QFont:
    font.setBold(True)
    return font


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
