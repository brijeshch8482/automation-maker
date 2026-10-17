"""Pydantic models for the AutomationSpec (docs/ARCHITECTURE.md §7).

These models check structure only. Cross-references (block names, `@settings.*`,
`{var}` placeholders, `out` names, network rules) are checked by `tools.validate_spec`.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

KEY_PATTERN = r"^[a-z][a-z0-9_]*$"
ID_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"
SEMVER_PATTERN = r"^\d+\.\d+\.\d+$"
BLOCK_PATTERN = r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$"

Key = Annotated[str, Field(pattern=KEY_PATTERN, max_length=64)]

Category = Literal["documents", "pdf", "images", "excel", "files", "convert", "other"]
CATEGORIES: tuple[str, ...] = Category.__args__


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Network(_Model):
    required: bool = False
    domains: list[str] = Field(default_factory=list)


# --- Fields (settings, inputs, table columns) -------------------------------------------


class _FieldBase(_Model):
    key: Key
    label: str | None = Field(default=None, max_length=120)
    required: bool = False
    help: str | None = Field(default=None, max_length=500)


class TextField(_FieldBase):
    type: Literal["text"]
    multiline: bool = False
    default: str | None = None


class NumberField(_FieldBase):
    type: Literal["number"]
    min: float | None = None
    max: float | None = None
    default: float | None = None


class MoneyField(_FieldBase):
    type: Literal["money"]
    currency: str = Field(default="INR", pattern=r"^[A-Z]{3}$")
    default: float | None = None


class PhoneField(_FieldBase):
    type: Literal["phone"]
    default: str | None = None


class EmailField(_FieldBase):
    type: Literal["email"]
    default: str | None = None


class DateField(_FieldBase):
    type: Literal["date"]
    default: Literal["today"] | None = None


class _PathFieldBase(_FieldBase):
    # Extensions without the dot, lower case, e.g. ["pdf"]. Empty means any file.
    extensions: list[Annotated[str, Field(pattern=r"^[a-z0-9]+$")]] = Field(default_factory=list)


class FileField(_PathFieldBase):
    type: Literal["file"]


class FilesField(_PathFieldBase):
    type: Literal["files"]
    min_count: int = Field(default=1, ge=0)


class ImageFileField(_FieldBase):
    type: Literal["image_file"]


class FolderField(_FieldBase):
    type: Literal["folder"]


class SelectField(_FieldBase):
    type: Literal["select"]
    options: list[str] = Field(min_length=1)
    default: str | None = None

    @model_validator(mode="after")
    def _default_in_options(self) -> SelectField:
        if self.default is not None and self.default not in self.options:
            raise ValueError(f"default {self.default!r} is not one of the options")
        if len(set(self.options)) != len(self.options):
            raise ValueError("options must be unique")
        return self


class CheckboxField(_FieldBase):
    type: Literal["checkbox"]
    default: bool = False


ColumnField = Annotated[
    TextField
    | NumberField
    | MoneyField
    | PhoneField
    | EmailField
    | DateField
    | SelectField
    | CheckboxField,
    Field(discriminator="type"),
]


class TableField(_FieldBase):
    type: Literal["table"]
    columns: list[ColumnField] = Field(min_length=1)
    min_rows: int = Field(default=0, ge=0)


SpecField = Annotated[
    TextField
    | NumberField
    | MoneyField
    | PhoneField
    | EmailField
    | DateField
    | FileField
    | FilesField
    | FolderField
    | ImageFileField
    | SelectField
    | CheckboxField
    | TableField,
    Field(discriminator="type"),
]

FIELD_TYPES: tuple[str, ...] = (
    "text",
    "number",
    "money",
    "phone",
    "email",
    "date",
    "file",
    "files",
    "folder",
    "image_file",
    "select",
    "checkbox",
    "table",
)


# --- Steps and output -------------------------------------------------------------------


class Step(_Model):
    block: str = Field(pattern=BLOCK_PATTERN)
    args: dict[str, Any] = Field(default_factory=dict)
    out: Key | None = None


class Output(_Model):
    type: Literal["file", "files", "folder", "none"]
    open_after: bool = False


# --- The spec ---------------------------------------------------------------------------


class AutomationSpec(_Model):
    """One automation. Source of truth for the web preview, EXE, tests and guide."""

    model_config = ConfigDict(extra="forbid", title="AutomationSpec")

    id: str = Field(pattern=ID_PATTERN, max_length=64)
    version: str = Field(pattern=SEMVER_PATTERN)
    title: str = Field(min_length=1, max_length=80)
    category: Category
    network: Network = Field(default_factory=Network)
    settings: list[SpecField] = Field(default_factory=list)
    inputs: list[SpecField] = Field(default_factory=list)
    steps: list[Step] = Field(min_length=1)
    output: Output
    # FAKE data only, used for smoke tests and guide screenshots.
    sample_data: dict[str, Any] = Field(default_factory=dict)
