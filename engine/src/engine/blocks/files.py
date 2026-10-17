from __future__ import annotations

from pathlib import Path

from engine.context import RunContext
from engine.errors import EngineError
from engine.fileutil import safe_filename, write_new_file
from engine.values import Document, SavedFile
from spec.catalog import FileSaveArgs


def save(ctx: RunContext, args: FileSaveArgs) -> SavedFile:
    document = ctx.value(args.source)
    if not isinstance(document, Document):
        raise EngineError("there is no document to save")
    folder_value = ctx.value(args.folder)
    folder = Path(folder_value) if folder_value else ctx.output_dir
    filename = safe_filename(ctx.render(args.name), document.extension)
    try:
        return SavedFile(write_new_file(folder, filename, document.data))
    except OSError as err:  # missing, not a folder, no permission, disk full
        raise EngineError(
            "couldn't save to the output folder. Check that it still exists and that you can "
            "save files there, or choose another folder in Settings"
        ) from err
