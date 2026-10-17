"""Values passed between steps."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Document:
    """A file produced in memory by a step, saved to disk only by file.save."""

    data: bytes
    extension: str  # without the dot, e.g. "pdf"


@dataclass(frozen=True)
class SavedFile:
    path: Path

    def __str__(self) -> str:
        return str(self.path)
