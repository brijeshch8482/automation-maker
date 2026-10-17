from __future__ import annotations

import re
import stat
from datetime import datetime
from pathlib import Path
from typing import Any

from engine.changes import TEMP_PREFIX
from engine.context import RunContext
from engine.errors import EngineError
from engine.fileutil import safe_filename, write_new_file
from engine.money import to_decimal
from engine.values import Document, FileInfo, Move, RenamePlan, SavedFile
from spec.catalog import FileSaveArgs, FilesRenameArgs, FilesScanArgs


def save(ctx: RunContext, args: FileSaveArgs) -> SavedFile:
    document = ctx.value(args.source)
    if not isinstance(document, Document):
        raise EngineError("there is no document to save")
    folder_value = ctx.value(args.folder)
    folder = Path(folder_value) if folder_value else ctx.output_dir
    filename = safe_filename(ctx.render(args.name), document.extension)
    try:
        return SavedFile(write_new_file(folder, filename, document.data))
    except OSError as err:  # missing, not a folder, no permission, disk full
        raise EngineError(
            "couldn't save to the output folder. Check that it still exists and that you can "
            "save files there, or choose another folder in Settings"
        ) from err


# --- files.scan ---------------------------------------------------------------------------


def _natural_key(name: str) -> list[Any]:
    """IMG_2 before IMG_10."""
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", name)]


def _hidden(path: Path, st: Any) -> bool:
    if path.name.startswith(".") or path.name.startswith(TEMP_PREFIX):
        return True
    attributes = getattr(st, "st_file_attributes", 0)  # Windows only
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_HIDDEN", 0))


def scan(ctx: RunContext, args: FilesScanArgs) -> list[FileInfo]:
    value = ctx.value(args.folder)
    folder = Path(value) if value else None
    if folder is None or not folder.is_dir():
        raise EngineError("choose a folder that exists")
    wanted = {e.lower() for e in args.extensions}
    found = []
    for entry in folder.iterdir():
        st = entry.stat()
        if not stat.S_ISREG(st.st_mode) or _hidden(entry, st):
            continue
        if wanted and entry.suffix.lower().lstrip(".") not in wanted:
            continue
        found.append(FileInfo(entry, datetime.fromtimestamp(st.st_mtime)))
    if args.sort == "modified":
        found.sort(key=lambda f: (f.modified, _natural_key(f.path.name)))
    else:
        found.sort(key=lambda f: _natural_key(f.path.name))
    return found


# --- files.rename ---------------------------------------------------------------------------


def rename(ctx: RunContext, args: FilesRenameArgs) -> RenamePlan:
    files = ctx.value(args.files)
    if not isinstance(files, list) or not all(isinstance(f, FileInfo) for f in files):
        raise EngineError("there is no list of files to rename")
    if not files:
        raise EngineError("there are no matching files in the folder")
    start = _start_number(ctx, args.start)

    # Names that stay put (other files in the folders) can't be taken; Windows ignores case.
    sources = {f.path for f in files}
    taken: set[tuple[Path, str]] = set()
    for folder in {f.path.parent for f in files}:
        for entry in folder.iterdir():
            if entry not in sources:
                taken.add((folder, entry.name.lower()))

    moves, unchanged, adjusted = [], 0, 0
    for i, info in enumerate(files):
        stem = ctx.render(
            args.name,
            {
                "n": str(start + i).zfill(args.pad),
                "name": info.path.stem,
                "date": info.modified.strftime("%Y-%m-%d"),
            },
        ).strip()
        if not stem:
            raise EngineError("the new name pattern gives an empty name")
        ext = info.path.suffix.lstrip(".")
        filename = safe_filename(f"{stem}.{ext}" if ext else stem, ext or None)
        unique = _unique(info.path.parent, filename, taken)
        adjusted += unique != filename
        taken.add((info.path.parent, unique.lower()))
        if unique == info.path.name:
            unchanged += 1
            continue
        moves.append(Move(info.path, info.path.with_name(unique)))

    folder = files[0].path.parent
    plan = RenamePlan(folder, tuple(moves), unchanged=unchanged, adjusted=adjusted)
    ctx.pending.append(plan)
    return plan


def _start_number(ctx: RunContext, start: str | int) -> int:
    raw = ctx.value(start) if isinstance(start, str) else start
    try:
        number = to_decimal(raw)
    except ValueError as err:
        raise EngineError("the start number is not a number") from err
    if number is None:
        return 1
    if number != number.to_integral() or number < 0:
        raise EngineError("the start number must be a whole number, 0 or more")
    return int(number)


def _unique(folder: Path, filename: str, taken: set[tuple[Path, str]]) -> str:
    stem, dot, ext = filename.rpartition(".")
    if not dot:
        stem, ext = filename, ""
    candidate, n = filename, 1
    while (folder, candidate.lower()) in taken:
        n += 1
        candidate = f"{stem} ({n}).{ext}" if ext else f"{stem} ({n})"
    return candidate
