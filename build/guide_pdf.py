"""Guide.pdf: how to start the app, what happens to your data, then every screen step by step.

Made from the screenshots the packaged app renders in guide mode (manifest.json + PNGs).
"""

from __future__ import annotations

import json
from pathlib import Path

from fpdf import FPDF
from PIL import Image

from engine.templates.fonts import latin1, setup_font
from spec.models import AutomationSpec

# Blocks that rename or move the user's files (same list as FILE_CHANGING_BLOCKS in the web).
FILE_CHANGING_BLOCKS = {"files.rename"}

INK = (15, 23, 42)
MUTED = (100, 116, 139)
ACCENT = (79, 70, 229)
BORDER = (203, 213, 225)
MARGIN = 18.0


class GuideError(Exception):
    pass


class _Guide(FPDF):
    def __init__(self, title: str) -> None:
        super().__init__(unit="mm", format="A4")
        self.set_margins(MARGIN, MARGIN, MARGIN)
        self.set_auto_page_break(True, margin=MARGIN)
        self.font = setup_font(self)
        self.title_text = title
        self.set_creator("MakeMyEXE")
        self.set_title(latin1(f"{title} - Guide", self.font))

    def footer(self) -> None:
        self.set_y(-12)
        self.style(8, color=MUTED)
        self.cell(0, 5, self.t(f"{self.title_text} - Guide - page {self.page_no()}"), align="C")

    def t(self, text: str) -> str:
        return latin1(text, self.font)

    def style(self, size: float, bold: bool = False, color=INK) -> None:
        self.set_font(self.font.family, "B" if bold else "", size)
        self.set_text_color(*color)

    def heading(self, text: str, size: float = 15) -> None:
        self.style(size, bold=True)
        self.multi_cell(0, size * 0.5, self.t(text), align="L", new_x="LMARGIN", new_y="NEXT")
        self.ln(2)

    def para(self, text: str, size: float = 10.5, color=INK) -> None:
        self.style(size, color=color)
        self.multi_cell(0, size * 0.52, self.t(text), align="L", new_x="LMARGIN", new_y="NEXT")
        self.ln(1.5)

    def bullets(self, items: list[str]) -> None:
        for item in items:
            self.style(10.5)
            self.cell(5, 5.5, "•" if self.font.unicode else "-")
            self.multi_cell(0, 5.5, self.t(item), align="L", new_x="LMARGIN", new_y="NEXT")
            self.ln(0.8)
        self.ln(2)


def make_guide(spec: AutomationSpec, screens_dir: Path, exe: str, out: Path) -> Path:
    try:
        manifest = json.loads((screens_dir / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        raise GuideError(f"guide screenshots are missing: {err}") from err

    pdf = _Guide(spec.title)
    pdf.add_page()
    _cover(pdf, spec, exe)
    _help(pdf)
    pdf.add_page()
    for n, screen in enumerate(manifest.get("screens", []), start=1):
        image = screens_dir / Path(screen["file"]).name
        if not image.is_file():
            raise GuideError(f"screenshot {screen['file']} is missing")
        _step(pdf, n, screen.get("caption", ""), image)
    out.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(out))
    return out


def _cover(pdf: _Guide, spec: AutomationSpec, exe: str) -> None:
    pdf.style(9, bold=True, color=ACCENT)
    pdf.cell(0, 5, "MakeMyEXE", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    pdf.heading(spec.title, size=24)
    if spec.description:
        pdf.para(spec.description, size=12, color=MUTED)
    pdf.ln(3)

    pdf.heading("Start the app")
    pdf.bullets(
        [
            "Unzip the download into a folder you keep, for example Documents. "
            "Keep the files in the folder together.",
            f"Double-click {exe}.exe. Nothing is installed and no administrator rights are needed.",
            "If Windows shows 'Windows protected your PC', click 'More info', then 'Run anyway'. "
            "Test builds are not signed yet, so Windows doesn't know the app.",
        ]
    )

    pdf.heading("Your data stays with you")
    online = spec.network.required
    changes_files = any(step.block in FILE_CHANGING_BLOCKS for step in spec.steps)
    pdf.bullets(
        [
            (
                f"This app connects only to: {', '.join(spec.network.domains)}."
                if online
                else "The app never connects to the internet. It works offline."
            ),
            (
                "Files are renamed only after you check a preview, and one click undoes it. "
                "Nothing is ever deleted."
                if changes_files
                else "Your original files are never changed. Results are saved as new files."
            ),
            f"Your settings are saved on this PC only, in %APPDATA%\\MakeMyEXE\\{spec.id}.",
            "No tracking and no automatic updates.",
        ]
    )


STEP_IMAGE_MAX_H = 104.0  # two steps per A4 page


def _step(pdf: _Guide, n: int, caption: str, image: Path) -> None:
    if pdf.get_y() + STEP_IMAGE_MAX_H + 22 > pdf.h - MARGIN:
        pdf.add_page()
    pdf.style(9, bold=True, color=ACCENT)
    pdf.cell(0, 5, f"STEP {n}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)
    pdf.para(caption, size=12)
    pdf.ln(1)
    with Image.open(image) as png:
        px_w, px_h = png.size
    box_w, box_h = pdf.w - 2 * MARGIN, STEP_IMAGE_MAX_H
    scale = min(box_w / px_w, box_h / px_h)
    w, h = px_w * scale, px_h * scale
    x, y = (pdf.w - w) / 2, pdf.get_y()
    pdf.image(str(image), x=x, y=y, w=w, h=h)
    pdf.set_draw_color(*BORDER)  # a thin frame, like a window on the desktop
    pdf.rect(x, y, w, h)
    pdf.set_y(y + h + 8)


def _help(pdf: _Guide) -> None:
    pdf.heading("If something goes wrong")
    pdf.bullets(
        [
            "Fields with a problem are highlighted; fix them and press Run again.",
            "If the app shows an error, press 'Copy error report' and send it to us. "
            "The report never contains what you typed or the names of your files.",
            "To start fresh, close the app and open it again. Your settings are kept.",
        ]
    )
