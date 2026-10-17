import json

import jsonschema

from spec.export_schema import SCHEMA_DIR, automation_spec_schema, main, rendered_files


def test_committed_schema_is_up_to_date():
    assert main(["--check"]) == 0, "run `uv run python -m spec.export_schema`"


def test_export_writes_files(tmp_path, capsys):
    assert main(["--out", str(tmp_path)]) == 0
    for name, content in rendered_files().items():
        assert (tmp_path / name).read_text(encoding="utf-8") == content
    assert main(["--out", str(tmp_path), "--check"]) == 0


def test_check_reports_stale_file(tmp_path, capsys):
    main(["--out", str(tmp_path)])
    (tmp_path / "block_catalog.json").write_text("{}\n", encoding="utf-8")
    assert main(["--out", str(tmp_path), "--check"]) == 1
    assert "stale" in capsys.readouterr().err


def test_json_schema_accepts_invoice_spec(invoice_spec):
    schema = json.loads((SCHEMA_DIR / "automation_spec.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(invoice_spec, schema)


def test_json_schema_rejects_unknown_field_type(invoice_spec):
    invoice_spec["inputs"].append({"key": "x", "type": "slider", "label": "X"})
    validator = jsonschema.Draft202012Validator(automation_spec_schema())
    assert not validator.is_valid(invoice_spec)
