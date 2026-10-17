"""Values passed between steps."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
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


@dataclass(frozen=True)
class FileInfo:
    """A file found by files.scan."""

    path: Path
    modified: datetime


@dataclass(frozen=True)
class Move:
    source: Path
    target: Path


@dataclass(frozen=True)
class RenamePlan:
    """Planned renames. Nothing on disk changes until the user confirms the preview."""

    folder: Path
    moves: tuple[Move, ...]
    unchanged: int = 0  # files that already have their new name
    adjusted: int = 0  # names that got " (2)" etc. because of a clash
