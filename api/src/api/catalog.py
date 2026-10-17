"""Ready-made automations, loaded from automations/*/spec.json and validated at startup."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from spec.validate import validate_spec

log = logging.getLogger(__name__)


class Catalog:
    def __init__(self, specs: dict[str, dict[str, Any]]) -> None:
        self._specs = specs

    @classmethod
    def load(cls, folder: Path) -> Catalog:
        specs: dict[str, dict[str, Any]] = {}
        for path in sorted(folder.glob("*/spec.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as err:
                log.error("skipping %s: %s", path, err)
                continue
            spec, issues = validate_spec(data)
            if spec is None or issues:
                log.error("skipping %s: %s", path, "; ".join(map(str, issues)))
                continue
            specs[spec.id] = data
        return cls(specs)

    def list(self) -> list[dict[str, Any]]:
        return sorted(self._specs.values(), key=lambda s: s["title"])

    def get(self, automation_id: str) -> dict[str, Any] | None:
        return self._specs.get(automation_id)
