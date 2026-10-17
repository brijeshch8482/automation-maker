"""The only API generated custom steps may use (ARCHITECTURE.md §8).

Read the user's inputs, write new files only into the output folder. No delete, no overwrite,
no subprocess and no network (tools.check_job enforces the imports).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from engine.context import RunContext
from engine.errors import EngineError
from engine.fileutil import safe_filename, write_new_file


class CustomContext:
    def __init__(self, ctx: RunContext) -> None:
        self._ctx = ctx

    def input(self, key: str) -> Any:
        return self._ctx.inputs.get(key)

    def setting(self, key: str) -> Any:
        return self._ctx.settings.get(key)

    def out(self, name: str) -> Any:
        return self._ctx.outs.get(name)

    def read_bytes(self, path: str | Path) -> bytes:
        """Read a file the user selected in a file/files/image_file/folder input."""
        target = Path(path).resolve()
        if not any(_within(target, allowed) for allowed in self._selected_paths()):
            raise EngineError("custom step tried to read a file the user did not select")
        return target.read_bytes()

    def save_bytes(self, filename: str, data: bytes) -> Path:
        """Save a NEW file in the output folder and return its path."""
        return write_new_file(self._ctx.output_dir, safe_filename(filename), data)

    def _selected_paths(self) -> list[Path]:
        paths: list[Path] = []
        for field in self._ctx.spec.inputs:
            value = self._ctx.inputs.get(field.key)
            if field.type in ("file", "image_file", "folder") and value:
                paths.append(Path(value).resolve())
            elif field.type == "files" and value:
                paths.extend(Path(v).resolve() for v in value)
        return paths


def _within(target: Path, allowed: Path) -> bool:
    return target == allowed or allowed in target.parents
