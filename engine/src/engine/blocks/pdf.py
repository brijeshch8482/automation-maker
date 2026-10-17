from __future__ import annotations

import io
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError

from engine.context import RunContext
from engine.errors import EngineError
from engine.values import Document
from spec.catalog import PdfMergeArgs


def merge(ctx: RunContext, args: PdfMergeArgs) -> Document:
    paths = [Path(p) for p in ctx.inputs.get(args.files) or []]
    if not paths:
        raise EngineError("choose at least one PDF")
    writer = PdfWriter()
    for n, path in enumerate(paths, start=1):
        try:
            reader = PdfReader(path)  # read only; originals are never changed
            if reader.is_encrypted:
                raise EngineError(f"file {n} is password-protected")
            writer.append(reader)
        except (OSError, PdfReadError) as err:
            raise EngineError(f"file {n} could not be read as a PDF") from err
    out = io.BytesIO()
    writer.write(out)
    return Document(out.getvalue(), "pdf")
