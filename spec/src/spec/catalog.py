"""Block catalog: every block a spec step may use, with its args schema and description.

The engine implements these blocks; this module is the contract between specs and the engine.
String args that point at other parts of the spec are annotated with a `Ref` or `Template`
marker so `tools.validate_spec` can check that they resolve.
"""

from __future__ import annotations

import types
import typing
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.fields import FieldInfo

from spec.models import KEY_PATTERN

# --- Reference markers ------------------------------------------------------------------


@dataclass(frozen=True)
class Ref:
    """Marks a string arg that names something defined elsewhere in the spec.

    kind="input":  an input key (optionally restricted to `field_types`).
    kind="value":  an input key, the `out` of an earlier step, or `@settings.<key>`.
    kind="column": a column key of the table input named by the arg `table_arg`.
    """

    kind: Literal["input", "value", "column"]
    field_types: tuple[str, ...] = ()
    table_arg: str | None = None


@dataclass(frozen=True)
class Template:
    """Marks a string arg with `{var}` placeholders (input keys or earlier step outs).

    `per_item` names extra placeholders the block fills in itself for each item it handles,
    e.g. {n} and {name} for every file files.rename renames.
    """

    per_item: tuple[str, ...] = ()


def InputRef(*field_types: str) -> Any:
    return Annotated[
        str,
        Ref("input", field_types=field_types),
        Field(json_schema_extra={"x-ref": "input", "x-field-types": list(field_types)}),
    ]


def ColumnRef(table_arg: str) -> Any:
    return Annotated[
        str,
        Ref("column", table_arg=table_arg),
        Field(json_schema_extra={"x-ref": "column", "x-table-arg": table_arg}),
    ]


ValueRef = Annotated[str, Ref("value"), Field(json_schema_extra={"x-ref": "value"})]
TemplateStr = Annotated[str, Template(), Field(json_schema_extra={"x-template": True})]
RENAME_VARS = ("n", "name", "date")
FileNameTemplate = Annotated[
    str,
    Template(per_item=RENAME_VARS),
    Field(
        min_length=1,
        max_length=200,
        json_schema_extra={"x-template": True, "x-per-item": list(RENAME_VARS)},
    ),
]
Name = Annotated[str, Field(pattern=KEY_PATTERN, max_length=64)]
TableInput = InputRef("table")
FilesInput = InputRef("files")
TableColumn = ColumnRef("table")


def find_marker(annotation: Any) -> Ref | Template | None:
    """Return the Ref/Template marker inside an annotation, looking through unions."""
    if typing.get_origin(annotation) is Annotated:
        for meta in annotation.__metadata__:
            if isinstance(meta, Ref | Template):
                return meta
        return find_marker(typing.get_args(annotation)[0])
    if typing.get_origin(annotation) in (typing.Union, types.UnionType):
        for member in typing.get_args(annotation):
            marker = find_marker(member)
            if marker is not None:
                return marker
    return None


def arg_marker(info: FieldInfo) -> Ref | Template | None:
    """The marker of a block arg. Pydantic moves top-level Annotated metadata to `metadata`."""
    for meta in info.metadata:
        if isinstance(meta, Ref | Template):
            return meta
    return find_marker(info.annotation)


# --- Block definitions ------------------------------------------------------------------


class BlockArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True)
class BlockDef:
    name: str
    description: str
    args: type[BlockArgs]
    # What the step's `out` holds.
    produces: str


class CounterNextArgs(BlockArgs):
    name: Name
    prefix: str = Field(default="", max_length=20)
    start: int = Field(default=1, ge=0)
    pad: int = Field(default=0, ge=0, le=12)


class LineTotalsArgs(BlockArgs):
    table: TableInput
    qty: TableColumn
    rate: TableColumn
    tax: ValueRef | float | None = None


class RenderTemplateArgs(BlockArgs):
    template: Name


class PdfMergeArgs(BlockArgs):
    files: FilesInput


class FileSaveArgs(BlockArgs):
    source: ValueRef
    folder: ValueRef
    name: TemplateStr


class FilesScanArgs(BlockArgs):
    folder: ValueRef
    # Lower-case extensions without the dot; empty means every file.
    extensions: list[Annotated[str, Field(pattern=r"^[a-z0-9]+$")]] = Field(default_factory=list)
    sort: Literal["name", "modified"] = "name"


class FilesRenameArgs(BlockArgs):
    files: ValueRef
    # New name without extension (the extension is kept): {n} counter, {name} old name,
    # {date} modified date (YYYY-MM-DD), plus input keys and earlier outs.
    name: FileNameTemplate
    start: ValueRef | int = 1
    pad: int = Field(default=0, ge=0, le=6)


class CustomStepArgs(BlockArgs):
    function: Annotated[str, Field(pattern=r"^[a-z_][a-z0-9_]*$")] = "run"
    description: str = Field(min_length=1, max_length=2000)


_BLOCKS = [
    BlockDef(
        "counter.next",
        "Next value of a local counter that persists between runs, as prefix + "
        "zero-padded number (e.g. INV-0007).",
        CounterNextArgs,
        produces="text",
    ),
    BlockDef(
        "calc.line_totals",
        "Per-row amount = qty x rate for a table input, plus subtotal, tax (percent) "
        "and grand total.",
        LineTotalsArgs,
        produces="object with rows, subtotal, tax, total",
    ),
    BlockDef(
        "pdf.render_template",
        "Render a PDF from a bundled template using the inputs, settings and earlier step outputs.",
        RenderTemplateArgs,
        produces="PDF document",
    ),
    BlockDef(
        "pdf.merge",
        "Merge the selected PDF files, in order, into one PDF. Originals are not changed.",
        PdfMergeArgs,
        produces="PDF document",
    ),
    BlockDef(
        "file.save",
        "Save a document produced by an earlier step to a folder under a new name. "
        "Never overwrites: adds a suffix if the name exists.",
        FileSaveArgs,
        produces="path of the saved file",
    ),
    BlockDef(
        "files.scan",
        "List the files directly inside a folder (no subfolders, hidden files skipped), "
        "optionally only some extensions, sorted naturally by name or by date modified.",
        FilesScanArgs,
        produces="list of files",
    ),
    BlockDef(
        "files.rename",
        "Plan new names for a list of files from a pattern. Nothing changes until the user "
        "confirms the preview; every rename goes to the undo log and clashes get ' (2)'.",
        FilesRenameArgs,
        produces="rename plan (applied after the preview)",
    ),
    BlockDef(
        "custom.step",
        "Run a generated custom function (custom_step.py) through the context API. "
        "Use only when no combination of blocks can do the job.",
        CustomStepArgs,
        produces="value returned by the function",
    ),
]

BLOCKS: dict[str, BlockDef] = {block.name: block for block in _BLOCKS}


def get_block(name: str) -> BlockDef | None:
    return BLOCKS.get(name)


def catalog_json_schema() -> dict[str, Any]:
    """The catalog as JSON: block name -> description, produces, args JSON Schema."""
    return {
        name: {
            "description": block.description,
            "produces": block.produces,
            "args": block.args.model_json_schema(),
        }
        for name, block in sorted(BLOCKS.items())
    }
