"""Load and validate spec.json."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from engine.errors import EngineError
from engine.fieldvalues import initial_values
from spec.models import AutomationSpec, SpecField
from spec.validate import validate_spec

PATH_TYPES = {"file", "files", "folder", "image_file"}


@dataclass(frozen=True)
class LoadedSpec:
    spec: AutomationSpec
    raw: dict[str, Any]
    dir: Path

    def sample_inputs(self, workspace: Path | None = None) -> dict[str, Any]:
        """Sample values. Sample file paths are relative to spec.json; with a `workspace`, those
        files are first copied there, so a run (e.g. renames) never touches the originals."""
        values = initial_values(self.spec.inputs, self.spec.sample_data)
        return self._resolve_paths(self.spec.inputs, values, workspace)

    def sample_settings(self, workspace: Path | None = None) -> dict[str, Any]:
        values = initial_values(self.spec.settings, self.spec.sample_data)
        return self._resolve_paths(self.spec.settings, values, workspace)

    def _resolve_paths(
        self, fields: list[SpecField], values: dict[str, Any], workspace: Path | None
    ) -> dict[str, Any]:
        for field in fields:
            value = values.get(field.key)
            if field.type not in PATH_TYPES or not value:
                continue
            if field.type == "files":
                values[field.key] = [self._sample_path(v, workspace) for v in value]
            else:
                values[field.key] = self._sample_path(value, workspace)
        return values

    def _sample_path(self, value: str, workspace: Path | None) -> str:
        relative = Path(value)
        if relative.is_absolute() or ".." in relative.parts:
            raise EngineError("sample_data paths must be relative to spec.json, without '..'")
        source = self.dir / relative
        if not source.exists():
            raise EngineError(f"sample file {relative.as_posix()} is missing next to spec.json")
        if workspace is None:
            return str(source)
        # samples/Holiday photos -> <workspace>/Holiday photos
        inside = (
            relative.parts[1:]
            if relative.parts[0] == "samples" and len(relative.parts) > 1
            else relative.parts
        )
        target = workspace.joinpath(*inside)
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                shutil.copytree(source, target)
            else:
                shutil.copy2(source, target)
        return str(target)


def load_spec(path: Path) -> LoadedSpec:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        raise EngineError("spec.json could not be read") from err
    spec, issues = validate_spec(raw)
    if spec is None or issues:
        # Issues name spec paths only (no user data), so they are safe to show.
        raise EngineError("spec.json is not valid: " + "; ".join(map(str, issues[:5])))
    return LoadedSpec(spec, raw, path.parent)
