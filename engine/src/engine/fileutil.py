"""File writing rules: new files only, never overwrite, Windows-safe names."""

from __future__ import annotations

import re
from pathlib import Path

from engine.errors import EngineError

_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
MAX_NAME = 150


def safe_filename(name: str, extension: str | None = None) -> str:
    name = _INVALID.sub("-", name).strip().rstrip(". ")
    stem, dot, ext = name.rpartition(".")
    if extension and (not dot or ext.lower() != extension.lower()):
        stem, ext = name, extension
    elif not dot:
        stem, ext = name, ""
    stem = stem[: MAX_NAME - len(ext) - 1].rstrip(". ") or "file"
    if stem.split(".")[0].upper() in _RESERVED:
        stem = f"_{stem}"
    return f"{stem}.{ext}" if ext else stem


def write_new_file(folder: Path, filename: str, data: bytes) -> Path:
    """Write `data` as a NEW file in `folder`. An existing file gets ' (2)', ' (3)'... instead."""
    folder.mkdir(parents=True, exist_ok=True)
    stem, dot, ext = filename.rpartition(".")
    if not dot:
        stem, ext = filename, ""
    for n in range(1, 1000):
        candidate = filename if n == 1 else f"{stem} ({n}){'.' + ext if ext else ''}"
        path = folder / candidate
        try:
            with path.open("xb") as fh:  # "x": fails instead of overwriting
                fh.write(data)
        except FileExistsError:
            continue
        return path
    raise EngineError("too many files with the same name in the output folder")
