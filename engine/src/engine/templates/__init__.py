"""Built-in document templates, referenced by name from pdf.render_template."""

from __future__ import annotations

from collections.abc import Callable

from engine.context import RunContext
from engine.templates.invoice import render_invoice

Template = Callable[[RunContext], bytes]

TEMPLATES: dict[str, Template] = {
    "invoice_basic": render_invoice,
}


def get_template(name: str) -> Template | None:
    return TEMPLATES.get(name)
