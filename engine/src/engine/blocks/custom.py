"""custom.step: run a generated function through the context API (engine/custom_api.py)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from engine.context import RunContext
from engine.custom_api import CustomContext
from engine.errors import EngineError
from engine.sandbox import confined
from engine.values import SavedFile
from spec.catalog import CustomStepArgs

MODULE_FILE = "custom_step.py"


def run(ctx: RunContext, args: CustomStepArgs) -> object:
    if ctx.spec_dir is None or not (ctx.spec_dir / MODULE_FILE).is_file():
        raise EngineError(f"{MODULE_FILE} is missing next to spec.json")
    spec = importlib.util.spec_from_file_location("custom_step", ctx.spec_dir / MODULE_FILE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Confined from the first line of generated code, module level included.
    with confined(ctx.output_dir, network=ctx.spec.network.required):
        spec.loader.exec_module(module)
        function = getattr(module, args.function, None)
        if not callable(function):
            raise EngineError(f"{MODULE_FILE} has no function {args.function}")
        result = function(CustomContext(ctx))
    # A file the step saved (ctx.save_bytes) is shown like file.save's: "Open file" and the guide.
    if isinstance(result, Path) and ctx.output_dir.resolve() in result.resolve().parents:
        return SavedFile(result)
    return result
