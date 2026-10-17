"""pdf.render_template: a PDF from a bundled template (fpdf2). Apart from pdf.merge (pypdf)."""

from __future__ import annotations

from engine.context import RunContext
from engine.errors import EngineError
from engine.templates import get_template
from engine.values import Document
from spec.catalog import RenderTemplateArgs


def render_template(ctx: RunContext, args: RenderTemplateArgs) -> Document:
    template = get_template(args.template)
    if template is None:
        raise EngineError(f"template {args.template} is not available")
    return Document(template(ctx), "pdf")
