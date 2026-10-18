"""The Hub window: installed automations, Add automation…, the MakeMyEXE ID, About.

Opening an automation starts it in its own process (engine/hub.py). The Hub itself makes no
network call: the website buttons open the browser.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices, QDragEnterEvent, QDropEvent, QGuiApplication
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from engine import __version__, hub
from engine.pack import PackError
from engine.store import AppStore, ImportPlan, ImportResult
from engine.ui.window import _button, _card, _footer, _scroll_page

WINDOW_SIZE = (720, 680)


def _label(text: str, name: str | None = None, wrap: bool = False) -> QLabel:
    label = QLabel(text)
    if name:
        label.setObjectName(name)
    label.setWordWrap(wrap)
    return label


def _badge(domains: list[str]) -> QLabel:
    badge = _label("🌐 Uses internet" if domains else "🔒 Works offline")
    badge.setObjectName("badgeOnline" if domains else "badge")
    if domains:
        badge.setToolTip("Connects only to: " + ", ".join(domains))
    badge.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    return badge


def _size(size: int) -> str:
    if size >= 1_000_000:
        return f"{size / 1_000_000:.1f} MB"
    return f"{max(size, 1000) // 1000} KB"


def _row(*widgets: QWidget, stretch_after: int | None = None) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(10)
    for i, widget in enumerate(widgets):
        row.addWidget(widget)
        if stretch_after == i:
            row.addStretch()
    return row


class ImportDialog(QDialog):
    """§5 step 3: name, version, offline or which sites, size, and what it replaces."""

    def __init__(self, plan: ImportPlan, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.plan = plan
        self.setWindowTitle("Add to MakeMyEXE")
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 18)
        layout.setSpacing(12)
        if plan.downgrade:
            heading = f"You already have a newer {plan.title}"
            body = (
                f"This file has version {plan.version}; version {plan.installed[0]} is "
                "installed. Keep the newer one, or use this older version instead? "
                "Both stay available."
            )
        else:
            heading = f"Add {plan.title} to MakeMyEXE?"
            body = f"Version {plan.version}"
            if plan.reinstall:
                body += ". This version is already added; adding it again repairs it."
            elif plan.replaces:
                body += f". Replaces version {plan.replaces}, which you can still switch back to."
        layout.addWidget(_label(heading, "previewTitle", wrap=True))
        layout.addWidget(_label(body, wrap=True))
        details = QHBoxLayout()
        details.addWidget(_badge(plan.network_domains))
        details.addWidget(_label(_size(plan.size_bytes), "help"))
        details.addStretch()
        layout.addLayout(details)
        if plan.network_domains:
            sites = ", ".join(plan.network_domains)
            layout.addWidget(_label(f"It connects only to: {sites}", "help", wrap=True))

        buttons = QHBoxLayout()
        buttons.addStretch()
        if plan.downgrade:
            self.secondary = QPushButton(f"Use {plan.version}")
            self.primary = QPushButton(f"Keep {plan.installed[0]}")
            # "Keep" is the safe default: it answers no to the import.
            self.secondary.clicked.connect(self.accept)
            self.primary.clicked.connect(self.reject)
        else:
            self.secondary = QPushButton("Cancel")
            self.primary = QPushButton("Add")
            self.secondary.clicked.connect(self.reject)
            self.primary.clicked.connect(self.accept)
        self.primary.setObjectName("primary")
        self.primary.setDefault(True)
        buttons.addWidget(self.secondary)
        buttons.addWidget(self.primary)
        layout.addLayout(buttons)


def ask(plan: ImportPlan, parent: QWidget | None = None) -> bool:
    return ImportDialog(plan, parent).exec() == QDialog.DialogCode.Accepted


class HubWindow(QMainWindow):
    def __init__(
        self,
        store: AppStore,
        *,
        confirm: Callable[[ImportPlan], bool] | None = None,
        launcher: Callable[[str, str | None], object] = hub.launch,
        open_url: Callable[[str], object] | None = None,
    ) -> None:
        super().__init__()
        self.store = store
        self.confirm = confirm or (lambda plan: ask(plan, self))
        self.launcher = launcher
        self.open_url = open_url or (lambda url: QDesktopServices.openUrl(QUrl(url)))
        self.makemyexe_id = hub.display_id(store.install_id())
        self.setWindowTitle("MakeMyEXE")
        self.resize(*WINDOW_SIZE)
        self.setAcceptDrops(True)

        header = QWidget()
        header.setObjectName("header")
        bar = QHBoxLayout(header)
        bar.setContentsMargins(24, 14, 24, 14)
        bar.addWidget(_label("MakeMyEXE", "title"))
        bar.addStretch()
        self.add_button = _button("Add automation…", self.choose_file, primary=True)
        bar.addWidget(self.add_button)

        self.notice = _label("", "notice", wrap=True)
        self.notice.hide()
        self.list_box = QWidget()
        self.list_layout = QVBoxLayout(self.list_box)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(12)
        self.about_button = _button("About", self.about)
        version = _label(f"Version {__version__}", "help")
        page = _scroll_page(
            self.notice,
            self.list_box,
            self._id_card(),
            footer=_footer(self.about_button, note=version),
        )

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(header)
        layout.addWidget(page, 1)
        self.setCentralWidget(central)
        self.refresh()

    # --- building ---

    def _id_card(self) -> QWidget:
        self.copy_button = _button("Copy", self.copy_id)
        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        line.addWidget(_label(self.makemyexe_id, "mono"))
        line.addWidget(self.copy_button)
        line.addStretch()
        help_ = _label(
            "Made on this PC. Paid and custom automations will use it to know they belong "
            "here. This app never sends it anywhere.",
            "help",
            wrap=True,
        )
        return _card(_label("Your MakeMyEXE ID", "fieldLabel"), row, help_)

    def _entry_card(self, entry: hub.HubEntry) -> QWidget:
        open_button = _button("Open", lambda: self.open_automation(entry.id), primary=True)
        open_button.setEnabled(entry.problem is None)
        top = QWidget()
        top.setLayout(
            _row(
                _label(entry.title, "cardTitle"),
                _badge(entry.network_domains),
                open_button,
                stretch_after=1,
            )
        )
        top.layout().setContentsMargins(0, 0, 0, 0)
        widgets: list[QWidget] = [top]
        if entry.description:
            widgets.append(_label(entry.description, "intro", wrap=True))
        if entry.problem:
            widgets.append(_label(entry.problem, "banner", wrap=True))
        version_row = QWidget()
        line = QHBoxLayout(version_row)
        line.setContentsMargins(0, 0, 0, 0)
        line.addWidget(_label("Version", "help"))
        if len(entry.versions) > 1:
            combo = QComboBox()
            combo.addItems(entry.versions)
            combo.setCurrentText(entry.version)
            combo.currentTextChanged.connect(
                lambda version, ident=entry.id: self.select_version(ident, version)
            )
            combo.setObjectName(f"versions-{entry.id}")
            line.addWidget(combo)
        else:
            line.addWidget(_label(entry.version, "help"))
        line.addStretch()
        widgets.append(version_row)
        card = _card(*widgets)
        card.setProperty("automation", entry.id)
        return card

    def _empty_card(self) -> QWidget:
        text = _label(
            "Get one on the website: press Add to MakeMyEXE there, then open the downloaded "
            "file. Or press Add automation… if you already have a .mmx file.",
            "intro",
            wrap=True,
        )
        website = _button("Open the website", lambda: self.open_url(hub.WEBSITE))
        website.setObjectName("link")
        return _card(_label("No automations yet", "cardTitle"), text, website)

    def refresh(self) -> None:
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            if widget := item.widget():
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        self.entries = hub.entries(self.store)
        for entry in self.entries:
            self.list_layout.addWidget(self._entry_card(entry))
        if not self.entries:
            self.list_layout.addWidget(self._empty_card())

    # --- actions ---

    def show_notice(self, text: str, error: bool = False) -> None:
        self.notice.setObjectName("banner" if error else "notice")
        self.notice.setText(text)
        self.notice.style().unpolish(self.notice)
        self.notice.style().polish(self.notice)
        self.notice.show()

    def choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Add automation", str(Path.home() / "Downloads"), "MakeMyEXE files (*.mmx)"
        )
        if path:
            self.import_path(Path(path))

    def import_path(self, path: Path) -> list[ImportResult] | None:
        try:
            results = hub.import_file(self.store, path, self.confirm)
        except PackError as err:
            self.show_notice(f"This file wasn't added. {err}", error=True)
            return None
        except OSError:
            self.show_notice("This file couldn't be read. Download it again.", error=True)
            return None
        added = [r.plan for r in results if r.imported]
        if added:
            names = ", ".join(f"{p.title} {p.version}" for p in added)
            where = " It's also in the Start menu." if hub.exe_path() else ""
            self.show_notice(f"Added {names}.{where}")
        else:
            self.notice.hide()
        self.refresh()
        return results

    def open_automation(self, automation_id: str) -> None:
        version = next((e.version for e in self.entries if e.id == automation_id), None)
        try:
            self.launcher(automation_id, version)
        except OSError:
            self.show_notice("This automation couldn't be started. Try again.", error=True)

    def select_version(self, automation_id: str, version: str) -> None:
        entry = next(e for e in self.entries if e.id == automation_id)
        self.store.select(automation_id, None if version == entry.versions[0] else version)
        self.refresh()

    def copy_id(self) -> None:
        QGuiApplication.clipboard().setText(self.makemyexe_id)
        self.show_notice("Your MakeMyEXE ID is copied.")

    def about(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("About MakeMyEXE")
        box.setText(
            f"MakeMyEXE {__version__}\n\nYour automations run on this PC. "
            "This app makes no internet connection and never updates by itself."
        )
        check = box.addButton("Check for updates on the website", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Close)
        box.exec()
        if box.clickedButton() is check:
            self.open_url(f"{hub.WEBSITE}/download")

    # --- drag and drop ---

    @staticmethod
    def _dropped(event: QDragEnterEvent | QDropEvent) -> list[Path]:
        urls = event.mimeData().urls() if event.mimeData().hasUrls() else []
        return [Path(u.toLocalFile()) for u in urls if u.toLocalFile().lower().endswith(".mmx")]

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self._dropped(event):
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        for path in self._dropped(event):
            self.import_path(path)
        event.acceptProposedAction()
