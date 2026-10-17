"""One widget per spec field type. Each exposes value() / set_value() / validate()."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from engine.money import to_decimal
from spec.models import ColumnField, SpecField

EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE = re.compile(r"^\+?[\d\s\-()]{6,20}$")
CURRENCY_SYMBOLS = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£"}
IMAGE_EXTENSIONS = ["png", "jpg", "jpeg", "bmp"]


def field_label(field: SpecField | ColumnField) -> str:
    return field.label or field.key.replace("_", " ").capitalize()


def compact_path(path: str) -> str:
    """Long paths are unreadable in a one-line box: show '…/parent/name', full path as tooltip."""
    if not path:
        return ""
    parts = Path(path).parts
    if len(parts) <= 3:
        return path
    return os.sep.join(["…", *parts[-2:]])


def display_text(value: Any) -> str:
    """How a stored value appears in a text box: 18.0 -> '18', None -> ''."""
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:g}" if value.is_integer() else repr(value)
    return str(value)


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or value == []


def check_scalar(field: SpecField | ColumnField, value: Any) -> str | None:
    """Validation shared by form fields and table cells. Messages name no values."""
    if field.required and _is_empty(value) and field.type != "checkbox":
        return "Required"
    if _is_empty(value):
        return None
    match field.type:
        case "number" | "money":
            try:
                number = to_decimal(value)
            except ValueError:
                return "Enter a number"
            if field.type == "number" and number is not None:
                if field.min is not None and number < field.min:
                    return f"Must be at least {field.min:g}"
                if field.max is not None and number > field.max:
                    return f"Must be at most {field.max:g}"
        case "email":
            if not EMAIL.match(str(value)):
                return "Enter an email address like name@example.com"
        case "phone":
            if not PHONE.match(str(value)):
                return "Enter a phone number"
    return None


class FieldWidget(QWidget):
    changed = Signal()

    def __init__(self, field: SpecField) -> None:
        super().__init__()
        self.field = field
        self.layout_ = QHBoxLayout(self)
        self.layout_.setContentsMargins(0, 0, 0, 0)
        self.layout_.setSpacing(6)

    def value(self) -> Any:
        raise NotImplementedError

    def set_value(self, value: Any) -> None:
        raise NotImplementedError

    def validate(self) -> str | None:
        return check_scalar(self.field, self.value())

    def set_invalid(self, invalid: bool) -> None:
        for child in self.findChildren(QWidget):
            if isinstance(child, QLineEdit | QPlainTextEdit):
                child.setProperty("invalid", invalid)
                child.style().unpolish(child)
                child.style().polish(child)


class LineField(FieldWidget):
    def __init__(self, field: SpecField) -> None:
        super().__init__(field)
        if field.type == "money":
            symbol = QLabel(CURRENCY_SYMBOLS.get(field.currency, field.currency))
            symbol.setObjectName("currency")
            self.layout_.addWidget(symbol)
        self.edit = QLineEdit()
        self.edit.setAccessibleName(field_label(field))
        if field.type in ("number", "money"):
            self.edit.setInputMethodHints(Qt.InputMethodHint.ImhFormattedNumbersOnly)
        self.edit.textChanged.connect(self.changed)
        self.layout_.addWidget(self.edit)

    def value(self) -> str:
        return self.edit.text().strip()

    def set_value(self, value: Any) -> None:
        self.edit.setText(display_text(value))


class TextAreaField(FieldWidget):
    def __init__(self, field: SpecField) -> None:
        super().__init__(field)
        self.edit = QPlainTextEdit()
        self.edit.setAccessibleName(field_label(field))
        self.edit.setFixedHeight(76)
        self.edit.textChanged.connect(self.changed)
        self.layout_.addWidget(self.edit)

    def value(self) -> str:
        return self.edit.toPlainText().strip()

    def set_value(self, value: Any) -> None:
        self.edit.setPlainText("" if value is None else str(value))


class DateField(FieldWidget):
    def __init__(self, field: SpecField) -> None:
        super().__init__(field)
        self.edit = QDateEdit()
        self.edit.setCalendarPopup(True)
        self.edit.setDisplayFormat("dd-MM-yyyy")
        self.edit.setDate(QDate.currentDate())
        self.edit.setAccessibleName(field_label(field))
        self.edit.dateChanged.connect(self.changed)
        self.layout_.addWidget(self.edit)
        self.layout_.addStretch()

    def value(self) -> str:
        return self.edit.date().toString(Qt.DateFormat.ISODate)

    def set_value(self, value: Any) -> None:
        date = QDate.fromString(str(value or ""), Qt.DateFormat.ISODate)
        self.edit.setDate(date if date.isValid() else QDate.currentDate())


class SelectField(FieldWidget):
    def __init__(self, field: SpecField) -> None:
        super().__init__(field)
        self.combo = QComboBox()
        self.combo.setAccessibleName(field_label(field))
        self.combo.addItem("Choose…", "")
        for option in field.options:
            self.combo.addItem(option, option)
        self.combo.currentIndexChanged.connect(self.changed)
        self.layout_.addWidget(self.combo)
        self.layout_.addStretch()

    def value(self) -> str:
        return self.combo.currentData() or ""

    def set_value(self, value: Any) -> None:
        index = self.combo.findData(value or "")
        self.combo.setCurrentIndex(max(index, 0))


class CheckField(FieldWidget):
    def __init__(self, field: SpecField) -> None:
        super().__init__(field)
        self.box = QCheckBox(field_label(field))
        self.box.toggled.connect(self.changed)
        self.layout_.addWidget(self.box)

    def value(self) -> bool:
        return self.box.isChecked()

    def set_value(self, value: Any) -> None:
        self.box.setChecked(bool(value))


class PathField(FieldWidget):
    """file, image_file and folder: a read-only path and a picker button."""

    def __init__(self, field: SpecField) -> None:
        super().__init__(field)
        self.edit = QLineEdit()
        self.edit.setReadOnly(True)
        self.edit.setAccessibleName(field_label(field))
        empty = {"folder": "No folder selected", "image_file": "No image selected"}
        self.edit.setPlaceholderText(empty.get(field.type, "No file selected"))
        button = QPushButton("Choose folder…" if field.type == "folder" else "Browse…")
        button.clicked.connect(self._pick)
        self.layout_.addWidget(self.edit, 1)
        self.layout_.addWidget(button)

        self._path = ""

    def _pick(self) -> None:
        if self.field.type == "folder":
            path = QFileDialog.getExistingDirectory(self, field_label(self.field))
        else:
            exts = IMAGE_EXTENSIONS if self.field.type == "image_file" else self.field.extensions
            pattern = " ".join(f"*.{e}" for e in exts) if exts else "*"
            path, _ = QFileDialog.getOpenFileName(
                self, field_label(self.field), "", f"Files ({pattern})"
            )
        if path:
            self.set_value(path)
            self.changed.emit()

    def value(self) -> str:
        return self._path

    def set_value(self, value: Any) -> None:
        self._path = str(value or "")
        self.edit.setText(compact_path(self._path))
        self.edit.setToolTip(self._path)


class FilesField(FieldWidget):
    """An ordered list of files (order matters, e.g. for merging PDFs)."""

    def __init__(self, field: SpecField) -> None:
        super().__init__(field)
        self.list = QListWidget()
        self.list.setAccessibleName(field_label(field))
        self.list.setFixedHeight(110)
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        buttons = QVBoxLayout()
        for text, slot in (("Add files…", self._add), ("Remove", self._remove)):
            button = QPushButton(text)
            button.clicked.connect(slot)
            buttons.addWidget(button)
        buttons.addStretch()
        self.layout_.addWidget(self.list, 1)
        self.layout_.addLayout(buttons)

    def _add(self) -> None:
        pattern = " ".join(f"*.{e}" for e in self.field.extensions) or "*"
        paths, _ = QFileDialog.getOpenFileNames(
            self, field_label(self.field), "", f"Files ({pattern})"
        )
        for path in paths:
            self._add_item(path)
        self.changed.emit()

    def _add_item(self, path: str) -> None:
        # Show the file name; keep the full path for the run and as a tooltip.
        item = QListWidgetItem(Path(path).name)
        item.setData(Qt.ItemDataRole.UserRole, path)
        item.setToolTip(path)
        self.list.addItem(item)

    def _remove(self) -> None:
        for item in self.list.selectedItems():
            self.list.takeItem(self.list.row(item))
        self.changed.emit()

    def value(self) -> list[str]:
        return [self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())]

    def set_value(self, value: Any) -> None:
        self.list.clear()
        for path in value or []:
            self._add_item(str(path))

    def validate(self) -> str | None:
        count = len(self.value())
        if self.field.required and count == 0:
            return "Required"
        if count and count < self.field.min_count:
            return f"Choose at least {self.field.min_count} files"
        return None


class TableField(FieldWidget):
    def __init__(self, field: SpecField) -> None:
        super().__init__(field)
        self.columns: list[ColumnField] = list(field.columns)
        box = QVBoxLayout()
        box.setSpacing(4)
        self.table = QTableWidget(0, len(self.columns))
        self.table.setAccessibleName(field_label(field))
        self.table.setHorizontalHeaderLabels([field_label(c) for c in self.columns])
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        for col, column in enumerate(self.columns):
            if column.type in ("number", "money", "checkbox", "date"):
                header.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
                header.resizeSection(col, 110)
            else:
                header.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
        self.table.setMinimumHeight(140)
        self.table.itemChanged.connect(self.changed)
        row_buttons = QHBoxLayout()
        add, remove = QPushButton("+ Add row"), QPushButton("Remove row")
        add.setObjectName("link")
        add.clicked.connect(lambda: self._add_row({}))
        remove.clicked.connect(self._remove_row)
        row_buttons.addWidget(add)
        row_buttons.addStretch()
        row_buttons.addWidget(remove)
        box.addWidget(self.table)
        box.addLayout(row_buttons)
        self.layout_.addLayout(box)

    def _add_row(self, values: dict[str, Any]) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        for col, column in enumerate(self.columns):
            value = values.get(column.key)
            if column.type == "checkbox":
                item = QTableWidgetItem()
                item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
                item.setCheckState(Qt.CheckState.Checked if value else Qt.CheckState.Unchecked)
                self.table.setItem(row, col, item)
            elif column.type == "select":
                combo = QComboBox()
                combo.addItem("", "")
                for option in column.options:
                    combo.addItem(option, option)
                combo.setCurrentIndex(max(combo.findData(value or ""), 0))
                self.table.setCellWidget(row, col, combo)
            else:
                item = QTableWidgetItem(display_text(value))
                if column.type in ("number", "money"):
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                self.table.setItem(row, col, item)
        self.changed.emit()

    def _remove_row(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        if not rows and self.table.rowCount():
            rows = [self.table.rowCount() - 1]
        for row in rows:
            self.table.removeRow(row)
        self.changed.emit()

    def value(self) -> list[dict[str, Any]]:
        rows = []
        for row in range(self.table.rowCount()):
            values: dict[str, Any] = {}
            for col, column in enumerate(self.columns):
                if column.type == "select":
                    widget = self.table.cellWidget(row, col)
                    values[column.key] = (
                        widget.currentData() if isinstance(widget, QComboBox) else ""
                    )
                    continue
                item = self.table.item(row, col)
                if column.type == "checkbox":
                    values[column.key] = (
                        item is not None and item.checkState() == Qt.CheckState.Checked
                    )
                else:
                    values[column.key] = item.text().strip() if item else ""
            rows.append(values)
        return rows

    def set_value(self, value: Any) -> None:
        self.table.setRowCount(0)
        for row in value or []:
            self._add_row(row)
        if not value:
            self._add_row({})  # one empty row to start typing in

    def validate(self) -> str | None:
        filled = [r for r in self.value() if any(v not in ("", False, None) for v in r.values())]
        if self.field.required and not filled:
            return "Add at least one row"
        if len(filled) < self.field.min_rows:
            return f"Add at least {self.field.min_rows} rows"
        for n, row in enumerate(filled, start=1):
            for column in self.columns:
                problem = check_scalar(column, row.get(column.key))
                if problem:
                    return f"Row {n}, {field_label(column)}: {problem.lower()}"
        return None


def make_field(field: SpecField) -> FieldWidget:
    match field.type:
        case "text":
            return TextAreaField(field) if field.multiline else LineField(field)
        case "number" | "money" | "phone" | "email":
            return LineField(field)
        case "date":
            return DateField(field)
        case "select":
            return SelectField(field)
        case "checkbox":
            return CheckField(field)
        case "file" | "image_file" | "folder":
            return PathField(field)
        case "files":
            return FilesField(field)
        case "table":
            return TableField(field)
    raise ValueError(f"unknown field type {field.type}")
