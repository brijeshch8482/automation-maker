"""Local data in %APPDATA%\\MakeMyEXE\\<id>\\: settings.json and SQLite counters. Never sent."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from collections.abc import Iterator
from contextlib import contextmanager
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
