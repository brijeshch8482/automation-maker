"""Look and feel. Colours match the web preview so the guide and the website agree."""

from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

ACCENT = "#4f46e5"
ACCENT_HOVER = "#4338ca"
INK = "#0f172a"
MUTED = "#64748b"
BORDER = "#cbd5e1"
ERROR = "#be123c"

STYLESHEET = f"""
QWidget {{ color: {INK}; font-size: 10pt; }}
QMainWindow, #page {{ background: #f8fafc; }}
#header {{ background: white; border-bottom: 1px solid #e2e8f0; }}
#title {{ font-size: 15pt; font-weight: 600; }}
#badge {{ background: #ecfdf5; color: #065f46; border: 1px solid #a7f3d0; border-radius: 9px; padding: 2px 8px; font-size: 8.5pt; }}
#badgeOnline {{ background: #fffbeb; color: #92400e; border: 1px solid #fde68a; border-radius: 9px; padding: 2px 8px; font-size: 8.5pt; }}
#card {{ background: white; border: 1px solid #e2e8f0; border-radius: 10px; }}
#intro {{ color: {MUTED}; }}
#fieldLabel {{ font-weight: 600; }}
#help {{ color: {MUTED}; font-size: 8.5pt; }}
#fieldError {{ color: {ERROR}; font-size: 8.5pt; }}
#banner {{ background: #fff1f2; color: {ERROR}; border: 1px solid #fecdd3; border-radius: 6px; padding: 8px; }}
#previewTitle {{ font-size: 14pt; font-weight: 600; }}
#resultTitle {{ font-size: 14pt; font-weight: 600; color: #065f46; }}
#errorTitle {{ font-size: 14pt; font-weight: 600; color: {ERROR}; }}
#currency {{ color: {MUTED}; }}
QLineEdit, QPlainTextEdit, QDateEdit, QComboBox, QListWidget, QTableWidget {{
    background: white; border: 1px solid {BORDER}; border-radius: 6px; padding: 5px 7px;
    selection-background-color: #c7d2fe; selection-color: {INK};
}}
QLineEdit:focus, QPlainTextEdit:focus, QDateEdit:focus, QComboBox:focus {{ border: 1px solid {ACCENT}; }}
QLineEdit[readOnly="true"] {{ background: #f8fafc; color: {MUTED}; }}
QLineEdit[invalid="true"], QPlainTextEdit[invalid="true"] {{ border: 1px solid {ERROR}; }}
QTableWidget {{ padding: 0; gridline-color: #e2e8f0; }}
QHeaderView::section {{ background: #f1f5f9; border: none; border-bottom: 1px solid #e2e8f0; padding: 5px; font-weight: 600; color: #475569; }}
QPushButton {{ background: white; border: 1px solid {BORDER}; border-radius: 6px; padding: 6px 12px; }}
QPushButton:hover {{ background: #f1f5f9; }}
QPushButton#primary {{ background: {ACCENT}; color: white; border: none; font-weight: 600; padding: 8px 18px; }}
QPushButton#primary:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#link {{ border: none; background: transparent; color: {ACCENT}; padding: 4px 0; text-align: left; }}
QScrollArea {{ border: none; background: transparent; }}
"""


def apply_theme(app: QApplication) -> None:
    font = QFont()
    font.setFamilies(["Segoe UI", "Inter", "DejaVu Sans", "Arial"])
    font.setPointSizeF(10)
    app.setFont(font)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)
