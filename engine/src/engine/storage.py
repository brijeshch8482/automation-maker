"""Local data in %APPDATA%\\MakeMyEXE\\<id>\\: settings.json and SQLite counters. Never sent."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

DATA_DIR_ENV = "MAKEMYEXE_DATA_DIR"


def default_data_root() -> Path:
    if override := os.environ.get(DATA_DIR_ENV):
        return Path(override)
    if sys.platform == "win32" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "MakeMyEXE"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "MakeMyEXE"


def default_output_dir(title: str) -> Path:
    """Where results go when the spec has no output folder setting, or it is empty."""
    safe = "".join(c for c in title if c.isalnum() or c in " -_").strip() or "Automation"
    return Path.home() / "Documents" / "MakeMyEXE" / safe


class Store:
    def __init__(self, automation_id: str, root: Path | None = None) -> None:
        self.dir = (root or default_data_root()) / automation_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self._settings = self.dir / "settings.json"
        self._db = self.dir / "data.sqlite3"
        with self._connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS counters (name TEXT PRIMARY KEY, value INTEGER)")
            # Undo log: every rename batch, recorded before it is applied (ARCHITECTURE.md §1.4).
            db.execute(
                "CREATE TABLE IF NOT EXISTS undo_batches (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "created TEXT NOT NULL, description TEXT NOT NULL, status TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS undo_moves (batch_id INTEGER NOT NULL, "
                "seq INTEGER NOT NULL, source TEXT NOT NULL, target TEXT NOT NULL, "
                "PRIMARY KEY (batch_id, seq))"
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Commit and CLOSE. sqlite3's own context manager only commits, which leaves the file
        open, and on Windows an open file can't be deleted or moved."""
        db = sqlite3.connect(self._db)
        try:
            with db:
                yield db
        finally:
            db.close()

    # --- settings ---

    def load_settings(self) -> dict[str, Any]:
        try:
            data = json.loads(self._settings.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def save_settings(self, values: dict[str, Any]) -> None:
        tmp = self._settings.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self._settings)  # our own file, so replacing it is fine

    # --- counters ---

    def counter_value(self, name: str) -> int | None:
        with self._connect() as db:
            row = db.execute("SELECT value FROM counters WHERE name = ?", (name,)).fetchone()
        return row[0] if row else None

    def set_counter(self, name: str, value: int) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT INTO counters (name, value) VALUES (?, ?) "
                "ON CONFLICT(name) DO UPDATE SET value = excluded.value",
                (name, value),
            )

    # --- undo log ---

    def record_batch(self, description: str, moves: list[tuple[str, str]]) -> int:
        """Record planned moves (status 'pending') before any file is touched."""
        with self._connect() as db:
            cursor = db.execute(
                "INSERT INTO undo_batches (created, description, status) VALUES (?, ?, 'pending')",
                (datetime.now().isoformat(timespec="seconds"), description),
            )
            batch_id = cursor.lastrowid
            assert batch_id is not None
            db.executemany(
                "INSERT INTO undo_moves (batch_id, seq, source, target) VALUES (?, ?, ?, ?)",
                [(batch_id, seq, src, dst) for seq, (src, dst) in enumerate(moves)],
            )
        return batch_id

    def set_batch_status(self, batch_id: int, status: str) -> None:
        with self._connect() as db:
            db.execute("UPDATE undo_batches SET status = ? WHERE id = ?", (status, batch_id))

    def batch(self, batch_id: int) -> tuple[str, list[tuple[str, str]]] | None:
        """(status, [(source, target), ...]) in the order they were applied."""
        with self._connect() as db:
            row = db.execute("SELECT status FROM undo_batches WHERE id = ?", (batch_id,)).fetchone()
            if row is None:
                return None
            moves = db.execute(
                "SELECT source, target FROM undo_moves WHERE batch_id = ? ORDER BY seq", (batch_id,)
            ).fetchall()
        return row[0], [(src, dst) for src, dst in moves]
