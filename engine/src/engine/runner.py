"""Runs a spec's steps in order."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from engine.blocks import get_block_impl
from engine.context import RunContext
from engine.errors import EngineError, StepError
from spec.catalog import get_block


@dataclass(frozen=True)
class RunResult:
    outs: dict[str, Any]
    last_value: Any  # what the last step produced, e.g. the saved file


def run(ctx: RunContext) -> RunResult:
    last: Any = None
    for index, step in enumerate(ctx.spec.steps):
        try:
            block = get_block(step.block)
            impl = get_block_impl(step.block)
            if block is None or impl is None:
                raise EngineError(f"block {step.block} is not available in this engine")
            args = block.args.model_validate(step.args)
            last = impl(ctx, args)
        except Exception as err:  # wrapped with the step for the error report
            raise StepError(index, step.block, err) from err
        if step.out:
            ctx.outs[step.out] = last
    for hook in ctx.on_success:
        hook()
    return RunResult(outs=dict(ctx.outs), last_value=last)
