"""Pick a Unicode TrueType font that exists on this PC (₹ and Indian scripts need one)."""

from __future__ import annotations

import contextlib
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from fpdf import FPDF


@dataclass(frozen=True)
class FontChoice:
    family: str
    unicode: bool

    @property
    def rupee(self) -> str:
        return "₹" if self.unicode else "Rs."


def _candidates() -> list[tuple[Path, Path]]:
    if sys.platform == "win32":
        fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        return [
            (fonts / "segoeui.ttf", fonts / "segoeuib.ttf"),
            (fonts / "arial.ttf", fonts / "arialbd.ttf"),
        ]
    return [
        (
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ),
        (Path("/Library/Fonts/Arial Unicode.ttf"), Path("/Library/Fonts/Arial Unicode.ttf")),
    ]


def _indic_candidates() -> list[tuple[Path, int]]:
    """Fonts covering Indian scripts (Devanagari, Tamil, Bengali...), with the TTC index."""
    if sys.platform == "win32":
        fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        return [(fonts / "Nirmala.ttc", 0), (fonts / "Nirmala.ttf", 0)]
    return [
        (Path("/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf"), 0),
        (Path("/usr/share/fonts/truetype/lohit-devanagari/Lohit-Devanagari.ttf"), 0),
    ]


def setup_font(pdf: FPDF) -> FontChoice:
    for regular, bold in _candidates():
        if regular.is_file() and bold.is_file():
            pdf.add_font("Body", "", str(regular))
            pdf.add_font("Body", "B", str(bold))
            _add_indic_fallback(pdf)
            return FontChoice("Body", unicode=True)
    return FontChoice("Helvetica", unicode=False)


def _add_indic_fallback(pdf: FPDF) -> None:
    """Names in Hindi and other Indian scripts: fall back to an Indic font, shaped with HarfBuzz."""
    for path, index in _indic_candidates():
        if path.is_file():
            pdf.add_font("Indic", "", str(path), collection_font_number=index)
            pdf.set_fallback_fonts(["Indic"], exact_match=False)
            break
    # Joins conjuncts like श्री (needs uharfbuzz); without it, Latin text is unaffected.
    with contextlib.suppress(Exception):
        pdf.set_text_shaping(True)


def latin1(text: str, font: FontChoice) -> str:
    """Core PDF fonts only cover Latin-1; replace what they can't show."""
    return text if font.unicode else text.encode("latin-1", "replace").decode("latin-1")
