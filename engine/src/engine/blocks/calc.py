from __future__ import annotations

from decimal import Decimal
from typing import Any

from engine.context import RunContext
from engine.errors import EngineError
from engine.money import round_money, to_decimal
from spec.catalog import LineTotalsArgs
from spec.models import TableField


def line_totals(ctx: RunContext, args: LineTotalsArgs) -> dict[str, Any]:
    table = next(f for f in ctx.spec.inputs if f.key == args.table)
    assert isinstance(table, TableField)
    labels = {c.key: c.label or c.key for c in table.columns}
    rows_in = ctx.inputs.get(args.table) or []

    rows, subtotal = [], Decimal(0)
    for n, row in enumerate(rows_in, start=1):
        if not any(str(v).strip() for v in row.values() if v is not None):
            continue  # an empty row the user didn't fill
        qty = _number(row.get(args.qty), n, labels[args.qty])
        rate = _number(row.get(args.rate), n, labels[args.rate])
        amount = round_money(qty * rate)
        subtotal += amount
        rows.append({**row, args.qty: qty, args.rate: rate, "amount": amount})
    if not rows:
        raise EngineError(f"add at least one row to {table.label or table.key}")

    tax_percent = _tax(ctx, args.tax)
    tax = round_money(subtotal * tax_percent / 100)
    return {
        "rows": rows,
        "subtotal": round_money(subtotal),
        "tax_percent": tax_percent,
        "tax": tax,
        "total": round_money(subtotal) + tax,
    }


def _number(value: Any, row: int, label: str) -> Decimal:
    try:
        number = to_decimal(value)
    except ValueError as err:
        raise EngineError(f"row {row}: {label} is not a number") from err
    if number is None:
        raise EngineError(f"row {row}: {label} is empty")
    if number < 0:
        raise EngineError(f"row {row}: {label} can't be negative")
    return number


def _tax(ctx: RunContext, tax: str | float | None) -> Decimal:
    if tax is None:
        return Decimal(0)
    raw = ctx.value(tax) if isinstance(tax, str) else tax
    try:
        percent = to_decimal(raw)
    except ValueError as err:
        raise EngineError("the tax percentage is not a number") from err
    if percent is None:
        return Decimal(0)
    if not 0 <= percent <= 100:
        raise EngineError("the tax percentage must be between 0 and 100")
    return percent
