"""Helpers for a custom job's own tests (jobs/<id>/test_custom_step.py, run by tools.check_job).

    from pathlib import Path

    from engine.testing import run_custom_step

    SPEC = Path(__file__).parent / "spec.json"


    def test_run_on_sample_data(tmp_path):
        saved = run_custom_step(SPEC, tmp_path)
        assert saved.path.read_text(encoding="utf-8").startswith("Words:")

run_custom_step runs the step exactly as the EXE does (engine.sandbox included) with the context
the EXE gives it: sample_data, sample files copied into tmp_path (the originals are never
touched), output into tmp_path/"output", and the outs of the steps before the custom.step.
sample_context and load_custom_step are for testing helper functions one by one.
"""

from __future__ import annotations

import importlib.util
from dataclasses import replace
from pathlib import Path
from types import ModuleType
from typing import Any

from engine.blocks import custom
from engine.blocks.custom import MODULE_FILE
from engine.context import RunContext
from engine.custom_api import CustomContext
from engine.loader import load_spec
from engine.runner import run
from engine.storage import Store
from spec.catalog import CustomStepArgs
from spec.models import AutomationSpec


def load_custom_step(spec_path: Path) -> ModuleType:
    """custom_step.py next to spec.json, imported the way the engine imports it."""
    path = Path(spec_path).parent / MODULE_FILE
    spec = importlib.util.spec_from_file_location("custom_step", path)
    assert spec and spec.loader, f"{MODULE_FILE} is missing next to spec.json"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sample_run_context(spec_path: Path, tmp_path: Path) -> RunContext:
    loaded = load_spec(Path(spec_path))
    workspace = tmp_path / "Sample files"
    ctx = RunContext(
        spec=loaded.spec,
        inputs=loaded.sample_inputs(workspace),
        settings=loaded.sample_settings(workspace),
        store=Store(loaded.spec.id, root=tmp_path / "data"),
        output_dir=tmp_path / "output",
        spec_dir=loaded.dir,
    )
    before = _steps_before_custom(loaded.spec)
    if before:
        # Shares ctx.outs, so the custom step sees what the earlier steps produced.
        run(replace(ctx, spec=loaded.spec.model_copy(update={"steps": loaded.spec.steps[:before]})))
    return ctx


def run_custom_step(spec_path: Path, tmp_path: Path) -> Any:
    """Run the spec's first custom.step on sample_data; a saved file comes back as SavedFile."""
    ctx = sample_run_context(spec_path, tmp_path)
    step = ctx.spec.steps[_steps_before_custom(ctx.spec)]
    return custom.run(ctx, CustomStepArgs.model_validate(step.args))


def sample_context(spec_path: Path, tmp_path: Path) -> CustomContext:
    """What the custom function receives when the EXE runs on sample_data."""
    return CustomContext(sample_run_context(spec_path, tmp_path))


def _steps_before_custom(spec: AutomationSpec) -> int:
    for i, step in enumerate(spec.steps):
        if step.block == "custom.step":
            return i
    return len(spec.steps)
