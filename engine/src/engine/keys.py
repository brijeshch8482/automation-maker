"""Public keys the Runner trusts for app packs (docs/ARCHITECTURE.md §8.3).

A released Runner trusts exactly the keys in build/trusted_keys.json, which build/runner.py
bundles as trusted_keys.json (`{key_id: hex}`). Run from source (development and tests), the
same file is read from the repository, plus a file named by MAKEMYEXE_TRUSTED_KEYS; that
variable is ignored by a frozen Runner.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

FILE_NAME = "trusted_keys.json"
REPO_FILE = Path(__file__).resolve().parents[3] / "build" / FILE_NAME


def parse_keys(text: str) -> dict[str, bytes]:
    data = json.loads(text)
    keys = {}
    for key_id, value in data.items():
        if key_id.startswith("_"):
            continue  # comments
        key = bytes.fromhex(value)
        if len(key) != 32:
            raise ValueError(f"key {key_id} is not a 32-byte Ed25519 public key")
        keys[key_id] = key
    return keys


def _read(path: Path) -> dict[str, bytes]:
    return parse_keys(path.read_text(encoding="utf-8")) if path.is_file() else {}


def trusted_keys() -> dict[str, bytes]:
    if getattr(sys, "frozen", False):
        return _read(Path(getattr(sys, "_MEIPASS", "")) / FILE_NAME)
    keys = _read(REPO_FILE)
    extra = os.environ.get("MAKEMYEXE_TRUSTED_KEYS")
    if extra:
        keys.update(_read(Path(extra)))
    return keys
