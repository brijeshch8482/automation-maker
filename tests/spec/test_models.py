import pytest
from pydantic import ValidationError

from spec import BLOCKS, FIELD_TYPES, AutomationSpec
from spec.catalog import BlockArgs, catalog_json_schema
from spec.models import SpecField, TableField


def test_invoice_spec_parses(invoice_spec):
    spec = AutomationSpec.model_validate(invoice_spec)
    assert spec.id == "invoice-generator"
    assert [s.block for s in spec.steps][-1] == "file.save"
    items = next(f for f in spec.inputs if f.key == "items")
    assert isinstance(items, TableField)
    assert [c.type for c in items.columns] == ["text", "number", "money"]


def test_field_types_cover_the_union():
    union_members = SpecField.__origin__.__args__
    assert {m.model_fields["type"].annotation.__args__[0] for m in union_members} == set(
        FIELD_TYPES
    )


@pytest.mark.parametrize("field_type", FIELD_TYPES)
def test_every_field_type_parses(invoice_spec, field_type):
    field = {"key": "f", "type": field_type, "label": "F"}
    if field_type == "select":
        field["options"] = ["a", "b"]
    if field_type == "table":
        field["columns"] = [{"key": "c", "type": "text"}]
    invoice_spec["inputs"].append(field)
    spec = AutomationSpec.model_validate(invoice_spec)
    assert spec.inputs[-1].type == field_type


def test_minimal_spec_defaults():
    spec = AutomationSpec.model_validate(
        {
            "id": "x",
            "version": "0.1.0",
            "title": "X",
            "category": "other",
            "steps": [{"block": "custom.step", "args": {"description": "do it"}}],
            "output": {"type": "none"},
        }
    )
    assert spec.network.required is False
    assert spec.network.domains == []
    assert spec.settings == spec.inputs == []
    assert spec.sample_data == {}


@pytest.mark.parametrize(
    ("mutate", "loc"),
    [
        (lambda s: s.update(id="Invoice Generator"), "id"),
        (lambda s: s.update(version="1.0"), "version"),
        (lambda s: s.update(category="finance"), "category"),
        (lambda s: s.update(steps=[]), "steps"),
        (lambda s: s.pop("output"), "output"),
        (lambda s: s.update(colour="red"), "colour"),
        (lambda s: s["inputs"].append({"key": "x", "type": "slider", "label": "X"}), "inputs"),
        (lambda s: s["inputs"].append({"key": "Bad Key", "type": "text"}), "inputs"),
        (lambda s: s["inputs"].append({"key": "s", "type": "select", "options": []}), "inputs"),
        (
            lambda s: s["inputs"].append(
                {"key": "s", "type": "select", "options": ["a"], "default": "b"}
            ),
            "inputs",
        ),
        (lambda s: s["inputs"].append({"key": "t", "type": "table", "columns": []}), "inputs"),
        (
            lambda s: s["inputs"].append(
                {"key": "t", "type": "table", "columns": [{"key": "f", "type": "file"}]}
            ),
            "inputs",
        ),
        (lambda s: s["steps"][0].update(block="counter"), "steps"),
        (lambda s: s["steps"][0].update(out="Invoice No"), "steps"),
        (lambda s: s["output"].update(type="email"), "output"),
        (lambda s: s["network"].update(proxy=True), "network"),
    ],
)
def test_structural_errors(invoice_spec, mutate, loc):
    mutate(invoice_spec)
    with pytest.raises(ValidationError) as exc:
        AutomationSpec.model_validate(invoice_spec)
    assert {e["loc"][0] for e in exc.value.errors()} == {loc}


def test_catalog_entries_are_well_formed():
    assert {"counter.next", "calc.line_totals", "pdf.render_template", "file.save"} <= set(BLOCKS)
    for name, block in BLOCKS.items():
        assert block.name == name
        assert block.description
        assert issubclass(block.args, BlockArgs)
    exported = catalog_json_schema()
    assert exported["file.save"]["args"]["properties"]["name"]["x-template"] is True
    assert exported["file.save"]["args"]["additionalProperties"] is False
