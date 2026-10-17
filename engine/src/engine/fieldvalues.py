"""Starting values for fields: sample data first, then the field's default, then empty.

Same rule as the web preview (web/src/lib/fields.ts).
"""

from __future__ import annotations

from datetime import date
from typing import Any

from spec.models import ColumnField, SpecField


def initial_value(
    field: SpecField | ColumnField, sample: dict[str, Any], today: date | None = None
) -> Any:
    if field.key in sample:
        return sample[field.key]
    match field.type:
        case "checkbox":
            return field.default
        case "table" | "files":
            return []
        case "date":
            return (today or date.today()).isoformat() if field.default == "today" else ""
        case "file" | "folder" | "image_file":
            return ""
        case _:
            default = getattr(field, "default", None)
            return "" if default is None else default


def initial_values(fields: list[SpecField], sample: dict[str, Any]) -> dict[str, Any]:
    return {f.key: initial_value(f, sample) for f in fields}
