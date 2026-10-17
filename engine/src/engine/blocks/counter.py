from __future__ import annotations

from engine.context import RunContext
from spec.catalog import CounterNextArgs


def next_value(ctx: RunContext, args: CounterNextArgs) -> str:
    """Next counter value. Saved only when the whole run succeeds, so failures leave no gaps."""
    current = ctx.store.counter_value(args.name)
    value = args.start if current is None else max(current + 1, args.start)
    ctx.on_success.append(lambda: ctx.store.set_counter(args.name, value))
    return f"{args.prefix}{value:0{args.pad}d}"
