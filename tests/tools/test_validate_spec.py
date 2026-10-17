import json

import pytest

from tools.validate_spec import Issue, format_loc, validate_spec
from tools.validate_spec.__main__ import main


def issues_of(data: dict) -> list[str]:
    return [str(issue) for issue in validate_spec(data)[1]]


def assert_one_issue(data: dict, path: str, fragment: str) -> None:
    issues = validate_spec(data)[1]
    assert len(issues) == 1, issues
    assert issues[0].path == path
    assert fragment in issues[0].message


def test_invoice_spec_is_valid(invoice_spec):
    spec, issues = validate_spec(invoice_spec)
    assert issues == []
    assert spec is not None and spec.id == "invoice-generator"


def test_valid_spec_using_every_reference_kind(invoice_spec):
    invoice_spec["network"] = {"required": True, "domains": ["api.example.com"]}
    invoice_spec["inputs"].append(
        {"key": "attachments", "type": "files", "label": "PDFs", "extensions": ["pdf"]}
    )
    invoice_spec["steps"] += [
        {"block": "pdf.merge", "args": {"files": "attachments"}, "out": "merged"},
        {
            "block": "file.save",
            "args": {
                "source": "merged",
                "folder": "@settings.output_folder",
                "name": "{invoice_no}-{customer_name}-{{copy}}.pdf",
            },
        },
        {"block": "custom.step", "args": {"description": "Log the invoice"}, "out": "log"},
    ]
    assert issues_of(invoice_spec) == []


# --- schema -----------------------------------------------------------------------------


def test_not_an_object():
    assert issues_of([]) == ["spec must be a JSON object"]  # type: ignore[arg-type]


def test_schema_errors_are_reported_with_paths(invoice_spec):
    invoice_spec["category"] = "finance"
    invoice_spec["inputs"][2]["columns"][1]["min"] = "zero"
    spec, issues = validate_spec(invoice_spec)
    assert spec is None
    paths = {issue.path for issue in issues}
    assert "category" in paths
    assert "inputs[2].table.columns[1].number.min" in paths


def test_format_loc():
    assert format_loc(("steps", 3, "args", "folder")) == "steps[3].args.folder"
    assert format_loc(()) == ""
    assert str(Issue("", "bad")) == "bad"


# --- fields -----------------------------------------------------------------------------


def test_duplicate_input_key(invoice_spec):
    invoice_spec["inputs"].append({"key": "customer_name", "type": "text", "label": "Again"})
    assert_one_issue(invoice_spec, "inputs[4]", "duplicate key 'customer_name'")


def test_duplicate_column_key(invoice_spec):
    invoice_spec["inputs"][2]["columns"].append({"key": "qty", "type": "number"})
    assert_one_issue(invoice_spec, "inputs[2].columns[3]", "duplicate column key 'qty'")


def test_setting_key_clashes_with_input(invoice_spec):
    invoice_spec["settings"].append({"key": "customer_name", "type": "text", "label": "X"})
    assert_one_issue(invoice_spec, "settings[4].key", "also an input key")


def test_missing_label(invoice_spec):
    del invoice_spec["settings"][1]["label"]
    assert_one_issue(invoice_spec, "settings[1].label", "needs a label")


# --- network ----------------------------------------------------------------------------


def test_network_required_without_domains(invoice_spec):
    invoice_spec["network"] = {"required": True, "domains": []}
    assert_one_issue(invoice_spec, "network.domains", "list the exact domains")


def test_domains_without_network_required(invoice_spec):
    invoice_spec["network"] = {"required": False, "domains": ["example.com"]}
    assert_one_issue(invoice_spec, "network.domains", "must be empty")


@pytest.mark.parametrize(
    "domain",
    [
        "https://example.com",
        "example.com/path",
        "example.com:443",
        "*.example.com",
        "Example.COM",
        "localhost",
        "",
    ],
)
def test_invalid_domain(invoice_spec, domain):
    invoice_spec["network"] = {"required": True, "domains": [domain]}
    assert_one_issue(invoice_spec, "network.domains[0]", "not a lower-case host name")


def test_duplicate_domain(invoice_spec):
    invoice_spec["network"] = {"required": True, "domains": ["a.example.com", "a.example.com"]}
    assert_one_issue(invoice_spec, "network.domains[1]", "duplicate domain")


# --- blocks and args --------------------------------------------------------------------


def test_unknown_block(invoice_spec):
    invoice_spec["steps"][2]["block"] = "pdf.render_magic"
    assert_one_issue(invoice_spec, "steps[2].block", "unknown block 'pdf.render_magic'")


def test_missing_required_arg(invoice_spec):
    del invoice_spec["steps"][3]["args"]["folder"]
    assert_one_issue(invoice_spec, "steps[3].args.folder", "Field required")


def test_unexpected_arg(invoice_spec):
    invoice_spec["steps"][0]["args"]["suffix"] = "-A"
    assert_one_issue(invoice_spec, "steps[0].args.suffix", "Extra inputs are not permitted")


def test_wrong_arg_type(invoice_spec):
    invoice_spec["steps"][0]["args"]["pad"] = "four"
    assert_one_issue(invoice_spec, "steps[0].args.pad", "valid integer")


def test_custom_step_needs_description(invoice_spec):
    invoice_spec["steps"].append({"block": "custom.step", "args": {"function": "run"}})
    assert_one_issue(invoice_spec, "steps[4].args.description", "Field required")


# --- references -------------------------------------------------------------------------


def test_unknown_setting_reference(invoice_spec):
    invoice_spec["steps"][3]["args"]["folder"] = "@settings.output_dir"
    assert_one_issue(invoice_spec, "steps[3].args.folder", "does not name a setting")


def test_unknown_reference_namespace(invoice_spec):
    invoice_spec["steps"][3]["args"]["folder"] = "@inputs.customer_name"
    assert_one_issue(invoice_spec, "steps[3].args.folder", "unknown reference")


def test_setting_reference_in_free_text_arg(invoice_spec):
    invoice_spec["steps"][0]["args"]["prefix"] = "@settings.nope"
    assert_one_issue(invoice_spec, "steps[0].args.prefix", "does not name a setting")


def test_unknown_input_key(invoice_spec):
    invoice_spec["steps"][1]["args"]["table"] = "lines"
    assert_one_issue(invoice_spec, "steps[1].args.table", "'lines' is not an input key")


def test_input_of_wrong_type(invoice_spec):
    invoice_spec["steps"][1]["args"]["table"] = "customer_name"
    assert_one_issue(invoice_spec, "steps[1].args.table", "is a text, expected table")


def test_unknown_column(invoice_spec):
    invoice_spec["steps"][1]["args"]["rate"] = "price"
    assert_one_issue(invoice_spec, "steps[1].args.rate", "'price' is not a column of table")


def test_unresolved_value_reference(invoice_spec):
    invoice_spec["steps"][3]["args"]["source"] = "document"
    assert_one_issue(invoice_spec, "steps[3].args.source", "'document' is not an input key")


def test_value_used_before_it_is_defined(invoice_spec):
    invoice_spec["steps"][1]["args"]["tax"] = "pdf"
    assert_one_issue(invoice_spec, "steps[1].args.tax", "used before step 2 defines it")


def test_numeric_tax_is_not_a_reference(invoice_spec):
    invoice_spec["steps"][1]["args"]["tax"] = 18
    assert issues_of(invoice_spec) == []


def test_unresolved_placeholder(invoice_spec):
    invoice_spec["steps"][3]["args"]["name"] = "{invoice_number}.pdf"
    assert_one_issue(invoice_spec, "steps[3].args.name", "{invoice_number} is not an input key")


def test_placeholder_used_before_defined(invoice_spec):
    invoice_spec["steps"].insert(
        0,
        {
            "block": "file.save",
            "args": {
                "source": "customer_name",
                "folder": "@settings.output_folder",
                "name": "{invoice_no}.txt",
            },
        },
    )
    assert_one_issue(invoice_spec, "steps[0].args.name", "{invoice_no} is used before step 1")


@pytest.mark.parametrize("name", ["{invoice_no.pdf", "invoice_no}.pdf"])
def test_malformed_template(invoice_spec, name):
    invoice_spec["steps"][3]["args"]["name"] = name
    assert_one_issue(invoice_spec, "steps[3].args.name", "bad template")


def test_empty_placeholder(invoice_spec):
    invoice_spec["steps"][3]["args"]["name"] = "{}.pdf"
    assert_one_issue(invoice_spec, "steps[3].args.name", "empty placeholder")


# --- outs -------------------------------------------------------------------------------


def test_duplicate_out(invoice_spec):
    invoice_spec["steps"][2]["out"] = "totals"
    issues = issues_of(invoice_spec)
    assert "steps[2].out: duplicate out 'totals'" in issues


def test_out_clashes_with_input_key(invoice_spec):
    invoice_spec["steps"][0]["out"] = "customer_name"
    invoice_spec["steps"][3]["args"]["name"] = "{customer_name}.pdf"
    assert_one_issue(invoice_spec, "steps[0].out", "clashes with an input key")


# --- sample data ------------------------------------------------------------------------


def test_sample_data_unknown_key(invoice_spec):
    invoice_spec["sample_data"]["customer_email"] = "a@example.com"
    assert_one_issue(invoice_spec, "sample_data.customer_email", "not an input or setting key")


def test_sample_data_missing_required_input(invoice_spec):
    del invoice_spec["sample_data"]["customer_name"]
    assert_one_issue(invoice_spec, "sample_data", "missing required input 'customer_name'")


def test_sample_data_table_not_rows(invoice_spec):
    invoice_spec["sample_data"]["items"] = {"description": "x"}
    assert_one_issue(invoice_spec, "sample_data.items", "list of row objects")


def test_sample_data_unknown_column(invoice_spec):
    invoice_spec["sample_data"]["items"][0]["discount"] = 5
    assert_one_issue(invoice_spec, "sample_data.items[0].discount", "not a column of 'items'")


def test_multiple_issues_are_all_reported(invoice_spec):
    invoice_spec["network"] = {"required": True, "domains": []}
    invoice_spec["steps"][2]["block"] = "nope.nope"
    invoice_spec["steps"][3]["args"]["folder"] = "@settings.missing"
    assert len(issues_of(invoice_spec)) == 3


# --- CLI --------------------------------------------------------------------------------


def test_cli_ok(capsys):
    assert main(["automations/invoice-generator/spec.json"]) == 0
    assert capsys.readouterr().out.startswith("OK")


def test_cli_reports_issues(tmp_path, invoice_spec, capsys):
    invoice_spec["steps"][3]["args"]["folder"] = "@settings.output_dir"
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(invoice_spec), encoding="utf-8")
    assert main([str(path)]) == 1
    out = capsys.readouterr().out
    assert "FAIL" in out
    assert "steps[3].args.folder: '@settings.output_dir' does not name a setting" in out


def test_cli_invalid_json(tmp_path, capsys):
    path = tmp_path / "spec.json"
    path.write_text("{not json", encoding="utf-8")
    assert main([str(path)]) == 1
    assert "not valid JSON" in capsys.readouterr().out


def test_cli_missing_file(tmp_path, capsys):
    assert main([str(tmp_path / "nope.json")]) == 1
    assert "cannot read file" in capsys.readouterr().out
