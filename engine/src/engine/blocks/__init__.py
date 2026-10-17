"""Block implementations, keyed like the catalog in spec/src/spec/catalog.py."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from engine.blocks import calc, counter, custom, files, makepdf, pdf
from engine.context import RunContext

BlockImpl = Callable[[RunContext, Any], Any]

IMPLEMENTATIONS: dict[str, BlockImpl] = {
    "counter.next": counter.next_value,
    "calc.line_totals": calc.line_totals,
    "pdf.render_template": pdf.render_template,
    "pdf.merge": pdf.merge,
    "pdf.from_files": makepdf.from_files,
    "file.save": files.save,
    "files.scan": files.scan,
    "files.rename": files.rename,
    "custom.step": custom.run,
}


def get_block_impl(name: str) -> BlockImpl | None:
    return IMPLEMENTATIONS.get(name)
