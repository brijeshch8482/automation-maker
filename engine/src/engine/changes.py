"""Applying and undoing file changes (renames) safely.

Rules (ARCHITECTURE.md §1): never delete, never overwrite, every change in the undo log.
Moves go through temporary names in the same folder (two phases), so swaps (a<->b) and
case-only renames on Windows work. If anything fails, the moves done so far are reversed.
"""

from __future__ import annotations

import contextlib
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from engine.errors import EngineError
from engine.storage import Store
from engine.values import Move, RenamePlan

TEMP_PREFIX = ".makemyexe-tmp-"


class _Clash(Exception):
    pass


def _move(source: Path, target: Path) -> None:
    """Rename without ever replacing an existing file (os.rename replaces on Linux/macOS)."""
    if target.exists() or target.is_symlink():
        raise _Clash(target.name)
    os.rename(source, target)


def _two_phase(moves: list[Move]) -> None:
    staged: list[tuple[Move, Path]] = []
    finished: list[tuple[Move, Path]] = []
    try:
        for move in moves:
            temp = move.source.with_name(f"{TEMP_PREFIX}{uuid.uuid4().hex}{move.source.suffix}")
            _move(move.source, temp)
            staged.append((move, temp))
        for move, temp in staged:
            _move(temp, move.target)
            finished.append((move, temp))
    except (OSError, _Clash) as err:
        # Put everything back where it was; best effort, never overwriting.
        for move, temp in reversed(finished):
            _quiet_move(move.target, temp)
        for move, temp in reversed(staged):
            _quiet_move(temp, move.source)
        raise EngineError(
            "couldn't rename the files (one may be open in another program, or a name is "
            "taken). Nothing was changed"
        ) from err


def _quiet_move(source: Path, target: Path) -> None:
    with contextlib.suppress(OSError, _Clash):
        _move(source, target)


def apply_plan(plan: RenamePlan, store: Store, description: str) -> int:
    """Apply a confirmed plan. Returns the undo batch id."""
    moves = list(plan.moves)
    batch_id = store.record_batch(description, [(str(m.source), str(m.target)) for m in moves])
    try:
        _two_phase(moves)
    except EngineError:
        store.set_batch_status(batch_id, "failed")
        raise
    store.set_batch_status(batch_id, "done")
    return batch_id


@dataclass(frozen=True)
class UndoResult:
    restored: int
    skipped: int  # renamed file missing, or its old name is now taken by another file


def undo(store: Store, batch_id: int) -> UndoResult:
    found = store.batch(batch_id)
    if found is None or found[0] != "done":
        raise EngineError("there is nothing to undo")
    _, recorded = found
    back = [Move(Path(dst), Path(src)) for src, dst in recorded if Path(dst).exists()]
    # An old name taken by a file that isn't moving away can't be restored. Dropping one move can
    # block another, so repeat until nothing changes.
    possible = back
    while True:
        moving_away = {m.source for m in possible}
        keep = [m for m in possible if not m.target.exists() or m.target in moving_away]
        if len(keep) == len(possible):
            break
        possible = keep
    _two_phase(possible)
    store.set_batch_status(batch_id, "undone")
    return UndoResult(restored=len(possible), skipped=len(recorded) - len(possible))
