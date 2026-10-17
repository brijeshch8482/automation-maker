"""Validate an AutomationSpec: schema, block catalog, references and network rules.

Used by the `am-spec` routine (via `python -m tools.validate_spec`) and by FastAPI on receipt.
"""

from __future__ import annotations

import re
import string
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from spec.catalog import Ref, Template, arg_marker, get_block
from spec.models import AutomationSpec, SpecField, TableField

SETTINGS_PREFIX = "@settings."
# Any string arg that starts like "@name." is a namespaced reference; only @settings exists.
NAMESPACED_REF = re.compile(r"^@[A-Za-z_]+\.")
HOSTNAME = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


@dataclass(frozen=True)
class Issue:
    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}" if self.path else self.message


def format_loc(loc: tuple[int | str, ...]) -> str:
    path = ""
    for part in loc:
        if isinstance(part, int):
            path += f"[{part}]"
        else:
            path += f".{part}" if path else str(part)
    return path


def _pydantic_issues(err: ValidationError, prefix: tuple[int | str, ...] = ()) -> list[Issue]:
    return [Issue(format_loc(prefix + tuple(e["loc"])), e["msg"]) for e in err.errors()]


def validate_spec(data: Any) -> tuple[AutomationSpec | None, list[Issue]]:
    """Return the parsed spec (None if the schema check failed) and every issue found."""
    if not isinstance(data, dict):
        return None, [Issue("", "spec must be a JSON object")]
    try:
        spec = AutomationSpec.model_validate(data)
    except ValidationError as err:
        return None, _pydantic_issues(err)

    issues = [
        *_check_fields(spec),
        *_check_network(spec),
        *_check_steps(spec),
        *_check_sample_data(spec),
    ]
    return spec, issues


# --- Fields -----------------------------------------------------------------------------


def _check_fields(spec: AutomationSpec) -> Iterator[Issue]:
    for section in ("settings", "inputs"):
        fields: list[SpecField] = getattr(spec, section)
        yield from _duplicates([f.key for f in fields], section, "key")
        for i, field in enumerate(fields):
            if not field.label:
                yield Issue(f"{section}[{i}].label", f"{field.key!r} needs a label")
            if isinstance(field, TableField):
                yield from _duplicates(
                    [c.key for c in field.columns], f"{section}[{i}].columns", "column key"
                )

    input_keys = {f.key for f in spec.inputs}
    for i, field in enumerate(spec.settings):
        if field.key in input_keys:
            yield Issue(f"settings[{i}].key", f"{field.key!r} is also an input key")


def _duplicates(keys: list[str], path: str, what: str) -> Iterator[Issue]:
    seen: set[str] = set()
    for i, key in enumerate(keys):
        if key in seen:
            yield Issue(f"{path}[{i}]", f"duplicate {what} {key!r}")
        seen.add(key)


# --- Network ----------------------------------------------------------------------------


def _check_network(spec: AutomationSpec) -> Iterator[Issue]:
    net = spec.network
    if not net.required:
        if net.domains:
            yield Issue("network.domains", "must be empty when network.required is false")
        return
    if not net.domains:
        yield Issue("network.domains", "list the exact domains when network.required is true")
    yield from _duplicates(net.domains, "network.domains", "domain")
    for i, domain in enumerate(net.domains):
        if not HOSTNAME.match(domain):
            yield Issue(
                f"network.domains[{i}]",
                f"{domain!r} is not a lower-case host name (no scheme, path, port or wildcard)",
            )


# --- Steps ------------------------------------------------------------------------------


class _Scope:
    """Names a step can refer to: inputs, settings and the outs of earlier steps."""

    def __init__(self, spec: AutomationSpec) -> None:
        self.inputs = {f.key: f for f in spec.inputs}
        self.settings = {f.key for f in spec.settings}
        self.outs: set[str] = set()

    def has_value(self, name: str) -> bool:
        return name in self.inputs or name in self.outs


def _check_steps(spec: AutomationSpec) -> Iterator[Issue]:
    scope = _Scope(spec)
    # out name -> index of the first step that defines it
    later_outs: dict[str, int] = {}
    for i, step in enumerate(spec.steps):
        if step.out:
            later_outs.setdefault(step.out, i)

    for i, step in enumerate(spec.steps):
        path = f"steps[{i}]"
        block = get_block(step.block)
        if block is None:
            yield Issue(f"{path}.block", f"unknown block {step.block!r}")
        else:
            try:
                args = block.args.model_validate(step.args)
            except ValidationError as err:
                yield from _pydantic_issues(err, (path, "args"))
            else:
                yield from _check_arg_refs(args, scope, later_outs, i, f"{path}.args")

        yield from _check_settings_refs(step.args, scope, f"{path}.args")

        if step.out:
            if step.out in scope.outs:
                yield Issue(f"{path}.out", f"duplicate out {step.out!r}")
            elif step.out in scope.inputs:
                yield Issue(f"{path}.out", f"out {step.out!r} clashes with an input key")
            scope.outs.add(step.out)


def _check_arg_refs(
    args: Any, scope: _Scope, later_outs: dict[str, int], step_index: int, path: str
) -> Iterator[Issue]:
    for name, info in type(args).model_fields.items():
        value = getattr(args, name)
        marker = arg_marker(info)
        if marker is None or not isinstance(value, str):
            continue
        arg_path = f"{path}.{name}"

        if isinstance(marker, Template):
            yield from _check_template(
                value, scope, later_outs, step_index, arg_path, marker.per_item
            )
        elif marker.kind == "value":
            # @settings.* strings are checked by _check_settings_refs.
            if not NAMESPACED_REF.match(value) and not scope.has_value(value):
                yield _unresolved(value, later_outs, step_index, arg_path)
        elif marker.kind == "input":
            yield from _check_input_ref(value, marker, scope, arg_path)
        elif marker.kind == "column":
            table = scope.inputs.get(getattr(args, marker.table_arg or ""))
            if isinstance(table, TableField) and value not in {c.key for c in table.columns}:
                yield Issue(arg_path, f"{value!r} is not a column of table {table.key!r}")


def _check_input_ref(value: str, marker: Ref, scope: _Scope, path: str) -> Iterator[Issue]:
    field = scope.inputs.get(value)
    if field is None:
        yield Issue(path, f"{value!r} is not an input key")
    elif marker.field_types and field.type not in marker.field_types:
        allowed = " or ".join(marker.field_types)
        yield Issue(path, f"input {value!r} is a {field.type}, expected {allowed}")


def _check_template(
    value: str,
    scope: _Scope,
    later_outs: dict[str, int],
    step_index: int,
    path: str,
    per_item: tuple[str, ...] = (),
) -> Iterator[Issue]:
    try:
        parsed = list(string.Formatter().parse(value))
    except ValueError as err:
        yield Issue(path, f"bad template {value!r}: {err}")
        return
    for _, field_name, _, _ in parsed:
        if field_name is None:
            continue
        var = re.split(r"[.\[]", field_name, maxsplit=1)[0]
        if not var:
            yield Issue(path, f"empty placeholder in {value!r}")
        elif var not in per_item and not scope.has_value(var):
            yield _unresolved(var, later_outs, step_index, path, placeholder=True)


def _unresolved(
    name: str, later_outs: dict[str, int], step_index: int, path: str, placeholder: bool = False
) -> Issue:
    what = f"{{{name}}}" if placeholder else repr(name)
    if later_outs.get(name, -1) >= step_index:
        return Issue(path, f"{what} is used before step {later_outs[name]} defines it")
    return Issue(path, f"{what} is not an input key or the out of an earlier step")


def _check_settings_refs(value: Any, scope: _Scope, path: str) -> Iterator[Issue]:
    """Every "@settings.<key>" string anywhere in the args must name a setting."""
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _check_settings_refs(item, scope, f"{path}.{key}")
    elif isinstance(value, list):
        for i, item in enumerate(value):
            yield from _check_settings_refs(item, scope, f"{path}[{i}]")
    elif isinstance(value, str) and NAMESPACED_REF.match(value):
        if not value.startswith(SETTINGS_PREFIX):
            yield Issue(path, f"unknown reference {value!r} (only @settings.<key> exists)")
        elif value.removeprefix(SETTINGS_PREFIX) not in scope.settings:
            yield Issue(path, f"{value!r} does not name a setting")


# --- Sample data ------------------------------------------------------------------------


def _check_sample_data(spec: AutomationSpec) -> Iterator[Issue]:
    fields = {f.key: f for f in [*spec.settings, *spec.inputs]}
    for key, value in spec.sample_data.items():
        path = f"sample_data.{key}"
        field = fields.get(key)
        if field is None:
            yield Issue(path, f"{key!r} is not an input or setting key")
        elif isinstance(field, TableField):
            yield from _check_sample_rows(field, value, path)

    for field in spec.inputs:
        if field.required and field.key not in spec.sample_data:
            yield Issue("sample_data", f"missing required input {field.key!r}")


def _check_sample_rows(table: TableField, rows: Any, path: str) -> Iterator[Issue]:
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        yield Issue(path, "table sample data must be a list of row objects")
        return
    columns = {c.key for c in table.columns}
    for i, row in enumerate(rows):
        for key in row:
            if key not in columns:
                yield Issue(f"{path}[{i}].{key}", f"{key!r} is not a column of {table.key!r}")
