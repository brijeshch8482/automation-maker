"""Exact money maths and Indian number formatting."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

PAISA = Decimal("0.01")


def to_decimal(value: Any) -> Decimal | None:
    """Parse a number from a form value; None for empty. Raises ValueError if not a number."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool):
        raise ValueError("not a number")
    try:
        number = Decimal(str(value).strip().replace(",", ""))
    except InvalidOperation as err:
        raise ValueError("not a number") from err
    if not number.is_finite():
        raise ValueError("not a number")
    return number


def round_money(value: Decimal) -> Decimal:
    return value.quantize(PAISA, rounding=ROUND_HALF_UP)


def format_indian(value: Decimal, decimals: int = 2) -> str:
    """1180000 -> '11,80,000.00' (lakh/crore grouping)."""
    quantum = Decimal(1).scaleb(-decimals)
    text = f"{abs(value.quantize(quantum, rounding=ROUND_HALF_UP)):.{decimals}f}"
    whole, _, frac = text.partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join([*groups, tail])
    sign = "-" if value < 0 else ""
    return f"{sign}{whole}.{frac}" if decimals else f"{sign}{whole}"


def format_number(value: Decimal) -> str:
    """Quantities without trailing zeros: Decimal('2.50') -> '2.5'."""
    text = f"{value:f}"
    return text.rstrip("0").rstrip(".") if "." in text else text
