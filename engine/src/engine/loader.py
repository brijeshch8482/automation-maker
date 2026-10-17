"""Load and validate spec.json."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from engine.errors import EngineError
from engine.fieldvalues import initial_values
from spec.models import AutomationSpec
from spec.validate import validate_spec


@dataclass(frozen=True)
class LoadedSpec:
    spec: AutomationSpec
    raw: dict[str, Any]
    dir: Path

    def sample_inputs(self) -> dict[str, Any]:
        return initial_values(self.spec.inputs, self.spec.sample_data)

    def sample_settings(self) -> dict[str, Any]:
        return initial_values(self.spec.settings, self.spec.sample_data)


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
