"""custom.step: run a generated function through the context API (engine/custom_api.py)."""

from __future__ import annotations

import importlib.util

from engine.context import RunContext
from engine.custom_api import CustomContext
from engine.errors import EngineError
from spec.catalog import CustomStepArgs

MODULE_FILE = "custom_step.py"


def run(ctx: RunContext, args: CustomStepArgs) -> object:
    if ctx.spec_dir is None or not (ctx.spec_dir / MODULE_FILE).is_file():
        raise EngineError(f"{MODULE_FILE} is missing next to spec.json")
    spec = importlib.util.spec_from_file_location("custom_step", ctx.spec_dir / MODULE_FILE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    function = getattr(module, args.function, None)
    if not callable(function):
        raise EngineError(f"{MODULE_FILE} has no function {args.function}")
    return function(CustomContext(ctx))
