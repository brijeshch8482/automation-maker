"""Block implementations, keyed like the catalog in spec/src/spec/catalog.py.

Modules are imported on first use, so a packaged EXE only contains the libraries of the blocks
its spec uses (build.package adds those modules as PyInstaller hidden imports).
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import Any

from engine.context import RunContext

BlockImpl = Callable[[RunContext, Any], Any]

# block name -> "module:function"
IMPLEMENTATIONS: dict[str, str] = {
    "counter.next": "engine.blocks.counter:next_value",
    "calc.line_totals": "engine.blocks.calc:line_totals",
    "pdf.render_template": "engine.blocks.template:render_template",
    "pdf.merge": "engine.blocks.pdf:merge",
    "pdf.from_files": "engine.blocks.makepdf:from_files",
    "file.save": "engine.blocks.files:save",
    "files.scan": "engine.blocks.files:scan",
    "files.rename": "engine.blocks.files:rename",
    "custom.step": "engine.blocks.custom:run",
}


def block_module(name: str) -> str | None:
    target = IMPLEMENTATIONS.get(name)
    return target.split(":")[0] if target else None


def get_block_impl(name: str) -> BlockImpl | None:
    target = IMPLEMENTATIONS.get(name)
    if target is None:
        return None
    module, function = target.split(":")
    return getattr(importlib.import_module(module), function)
