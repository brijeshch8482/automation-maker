"""Run context: what steps can read, and how spec references resolve."""

from __future__ import annotations

import string
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from engine.errors import EngineError
from engine.storage import Store
from engine.values import RenamePlan
from spec.models import AutomationSpec

SETTINGS_PREFIX = "@settings."


@dataclass
class RunContext:
    spec: AutomationSpec
    inputs: dict[str, Any]
    settings: dict[str, Any]
    store: Store
    output_dir: Path
    spec_dir: Path | None = None  # folder of spec.json (templates, custom_step.py)
    today: date = field(default_factory=date.today)
    outs: dict[str, Any] = field(default_factory=dict)
    # File changes planned by steps; applied only after the user confirms the preview.
    pending: list[RenamePlan] = field(default_factory=list)
    # Run only if every step succeeds (e.g. advancing an invoice counter).
    on_success: list[Callable[[], None]] = field(default_factory=list)

    def value(self, ref: str) -> Any:
        """Resolve a ValueRef: `@settings.<key>`, an input key, or an earlier step's out."""
        if ref.startswith(SETTINGS_PREFIX):
            return self.settings.get(ref.removeprefix(SETTINGS_PREFIX))
        if ref in self.outs:
            return self.outs[ref]
        if ref in self.inputs or any(f.key == ref for f in self.spec.inputs):
            return self.inputs.get(ref)
        raise EngineError(f"unknown reference '{ref}'")

    def render(self, template: str, extra: dict[str, Any] | None = None) -> str:
        """Fill a `{var}` template from `extra` (per-item values such as {n}), outs and inputs."""
        out = []
        for literal, name, spec, conversion in string.Formatter().parse(template):
            out.append(literal)
            if name is None:
                continue
            value = extra[name] if extra and name in extra else self.value(name)
            if value is None:
                value = ""
            if conversion:
                value = repr(value) if conversion == "r" else str(value)
            out.append(format(value, spec or ""))
        return "".join(out)

    def lookup(self) -> dict[str, Any]:
        """Everything a template or custom step may read, by name."""
        return {
            **self.inputs,
            **{f"settings.{k}": v for k, v in self.settings.items()},
            **self.outs,
        }
