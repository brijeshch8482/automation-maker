from decimal import Decimal

import pytest
from pypdf import PdfReader, PdfWriter

from engine.blocks import calc, counter, custom, files, pdf, template
from engine.context import RunContext
from engine.errors import EngineError
from engine.loader import LoadedSpec, load_spec
from engine.sandbox import SandboxError
from engine.values import Document, SavedFile
from spec.catalog import (
    CounterNextArgs,
    CustomStepArgs,
    FileSaveArgs,
    LineTotalsArgs,
    PdfMergeArgs,
    RenderTemplateArgs,
)
from tests.engine.conftest import write_pdf

TOTALS = LineTotalsArgs(table="items", qty="qty", rate="rate", tax="tax_percent")


# --- counter.next -----------------------------------------------------------------------


def test_counter_formats_and_saves_only_on_success(make_ctx, store):
    args = CounterNextArgs(name="invoice_no", prefix="INV-", start=7, pad=4)
    ctx = make_ctx()
    assert counter.next_value(ctx, args) == "INV-0007"
    assert store.counter_value("invoice_no") is None  # not yet: the run hasn't finished
    for hook in ctx.on_success:
        hook()
    assert store.counter_value("invoice_no") == 7
    assert counter.next_value(make_ctx(), args) == "INV-0008"


def test_counter_respects_a_raised_start(make_ctx, store):
    store.set_counter("n", 3)
    assert counter.next_value(make_ctx(), CounterNextArgs(name="n", start=10)) == "10"


# --- calc.line_totals -------------------------------------------------------------------


def test_line_totals_with_sample_data(make_ctx):
    result = calc.line_totals(make_ctx(), TOTALS)
    assert [r["amount"] for r in result["rows"]] == [Decimal("1000.00"), Decimal("1800.00")]
    assert result["subtotal"] == Decimal("2800.00")
    assert result["tax_percent"] == Decimal(18)
    assert result["tax"] == Decimal("504.00")
    assert result["total"] == Decimal("3304.00")


def test_line_totals_rounds_half_up_and_skips_empty_rows(make_ctx, invoice):
    inputs = {
        **invoice.sample_inputs(),
        "items": [
            {"description": "a", "qty": "3", "rate": "0.335"},
            {"description": "", "qty": "", "rate": ""},
        ],
        "tax_percent": "5",
    }
    result = calc.line_totals(make_ctx(inputs=inputs), TOTALS)
    assert len(result["rows"]) == 1
    assert result["rows"][0]["amount"] == Decimal("1.01")  # 1.005 -> 1.01
    assert result["tax"] == Decimal("0.05")


@pytest.mark.parametrize(
    ("items", "tax", "message"),
    [
        ([{"description": "a", "qty": "two", "rate": "5"}], "18", "row 1: qty is not a number"),
        ([{"description": "a", "qty": "1", "rate": ""}], "18", "row 1: rate is empty"),
        ([{"description": "a", "qty": "-1", "rate": "5"}], "18", "can't be negative"),
        ([], "18", "add at least one row"),
        ([{"description": "a", "qty": "1", "rate": "5"}], "abc", "tax percentage is not a number"),
        ([{"description": "a", "qty": "1", "rate": "5"}], "120", "between 0 and 100"),
    ],
)
def test_line_totals_errors_name_no_values(make_ctx, invoice, items, tax, message):
    inputs = {**invoice.sample_inputs(), "items": items, "tax_percent": tax}
    with pytest.raises(EngineError, match=message) as exc:
        calc.line_totals(make_ctx(inputs=inputs), TOTALS)
    assert "two" not in str(exc.value) and "abc" not in str(exc.value)


def test_line_totals_tax_options(make_ctx, invoice):
    inputs = {**invoice.sample_inputs(), "tax_percent": ""}
    assert calc.line_totals(make_ctx(inputs=inputs), TOTALS)["tax"] == 0
    numeric = LineTotalsArgs(table="items", qty="qty", rate="rate", tax=12)
    assert calc.line_totals(make_ctx(), numeric)["tax"] == Decimal("336.00")
    none = LineTotalsArgs(table="items", qty="qty", rate="rate")
    assert calc.line_totals(make_ctx(), none)["total"] == Decimal("2800.00")


# --- pdf ----------------------------------------------------------------------------------


def test_render_invoice(make_ctx, tmp_path):
    ctx = make_ctx()
    ctx.outs["invoice_no"] = "INV-0042"
    ctx.outs["totals"] = calc.line_totals(ctx, TOTALS)
    doc = template.render_template(ctx, RenderTemplateArgs(template="invoice_basic"))
    assert doc.extension == "pdf"
    path = tmp_path / "x.pdf"
    path.write_bytes(doc.data)
    text = PdfReader(path).pages[0].extract_text()
    for expected in (
        "Sample Business",
        "INV-0042",
        "17-10-2026",
        "Asha Traders",
        "Another sample item",
        "2,800.00",
        "GST 18%",
        "504.00",
        "3,304.00",
    ):
        assert expected in text


def test_render_invoice_with_unicode_and_logo(make_ctx, invoice, tmp_path):
    from PIL import Image

    logo = tmp_path / "logo.png"
    Image.new("RGB", (40, 40), (79, 70, 229)).save(logo)
    ctx = make_ctx(
        inputs={
            **invoice.sample_inputs(),
            "customer_name": "श्री ट्रेडर्स",
            "customer_phone": "+91 00000 00000",
        },
        settings={**invoice.sample_settings(), "gstin": "SAMPLE-GSTIN", "logo": str(logo)},
    )
    ctx.outs["totals"] = calc.line_totals(ctx, TOTALS)
    doc = template.render_template(ctx, RenderTemplateArgs(template="invoice_basic"))
    assert doc.data.startswith(b"%PDF")


def test_unknown_template_and_missing_totals(make_ctx):
    with pytest.raises(EngineError, match="not available"):
        template.render_template(make_ctx(), RenderTemplateArgs(template="nope"))
    with pytest.raises(EngineError, match=r"calc\.line_totals"):
        template.render_template(make_ctx(), RenderTemplateArgs(template="invoice_basic"))


def merge_spec(tmp_path) -> LoadedSpec:
    import json

    spec = {
        "id": "pdf-merge-test",
        "version": "1.0.0",
        "title": "PDF Merge",
        "category": "pdf",
        "inputs": [
            {
                "key": "pdfs",
                "type": "files",
                "label": "PDFs",
                "extensions": ["pdf"],
                "required": True,
            }
        ],
        "steps": [
            {"block": "pdf.merge", "args": {"files": "pdfs"}, "out": "merged"},
            {
                "block": "file.save",
                "args": {"source": "merged", "folder": "pdfs", "name": "merged.pdf"},
            },
        ],
        "output": {"type": "file"},
        "sample_data": {"pdfs": ["a.pdf", "b.pdf"]},
    }
    path = tmp_path / "merge" / "spec.json"
    path.parent.mkdir()
    path.write_text(json.dumps(spec))
    return load_spec(path)


def test_merge_keeps_order_and_originals(make_ctx, tmp_path):
    a = write_pdf(tmp_path / "a.pdf", 2, "A")
    b = write_pdf(tmp_path / "b.pdf", 1, "B")
    before = a.read_bytes()
    loaded = merge_spec(tmp_path)
    doc = pdf.merge(
        make_ctx(inputs={"pdfs": [str(b), str(a)]}, loaded=loaded), PdfMergeArgs(files="pdfs")
    )
    out = tmp_path / "m.pdf"
    out.write_bytes(doc.data)
    reader = PdfReader(out)
    assert len(reader.pages) == 3
    assert "B 1" in reader.pages[0].extract_text()
    assert a.read_bytes() == before


def test_merge_errors(make_ctx, tmp_path):
    loaded = merge_spec(tmp_path)
    with pytest.raises(EngineError, match="at least one"):
        pdf.merge(make_ctx(inputs={"pdfs": []}, loaded=loaded), PdfMergeArgs(files="pdfs"))
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a pdf")
    with pytest.raises(EngineError, match="file 1 could not be read"):
        pdf.merge(make_ctx(inputs={"pdfs": [str(bad)]}, loaded=loaded), PdfMergeArgs(files="pdfs"))
    locked = tmp_path / "locked.pdf"
    writer = PdfWriter(clone_from=write_pdf(tmp_path / "plain.pdf", 1))
    writer.encrypt("secret")
    writer.write(locked)
    with pytest.raises(EngineError, match="password-protected"):
        pdf.merge(
            make_ctx(inputs={"pdfs": [str(locked)]}, loaded=loaded), PdfMergeArgs(files="pdfs")
        )


# --- file.save ------------------------------------------------------------------------------


def test_save_uses_setting_folder_and_template(make_ctx, tmp_path):
    ctx = make_ctx(settings={"business_name": "B", "output_folder": str(tmp_path / "invoices")})
    ctx.outs.update(invoice_no="INV/7", pdf=Document(b"%PDF-1.4", "pdf"))
    saved = files.save(
        ctx, FileSaveArgs(source="pdf", folder="@settings.output_folder", name="{invoice_no}.pdf")
    )
    assert saved == SavedFile(tmp_path / "invoices" / "INV-7.pdf")


def test_save_falls_back_to_default_folder(make_ctx, tmp_path):
    ctx = make_ctx(settings={"business_name": "B", "output_folder": ""})
    ctx.outs.update(invoice_no="INV-1", pdf=Document(b"x", "pdf"))
    args = FileSaveArgs(source="pdf", folder="@settings.output_folder", name="{invoice_no}")
    assert files.save(ctx, args).path == tmp_path / "out" / "INV-1.pdf"
    assert files.save(ctx, args).path == tmp_path / "out" / "INV-1 (2).pdf"


def test_save_needs_a_document(make_ctx):
    ctx = make_ctx()
    ctx.outs["pdf"] = "not a document"
    with pytest.raises(EngineError, match="no document"):
        files.save(ctx, FileSaveArgs(source="pdf", folder="@settings.output_folder", name="x.pdf"))


# --- custom.step ----------------------------------------------------------------------------


def custom_ctx(make_ctx, tmp_path, code: str) -> RunContext:
    loaded = merge_spec(tmp_path)
    (loaded.dir / "custom_step.py").write_text(code)
    return make_ctx(inputs={"pdfs": [str(write_pdf(tmp_path / "in.pdf", 1))]}, loaded=loaded)


def test_custom_step_reads_selected_files_and_saves_new_ones(make_ctx, tmp_path):
    code = (
        "def run(ctx):\n"
        "    data = ctx.read_bytes(ctx.input('pdfs')[0])\n"
        "    return ctx.save_bytes('copy.pdf', data)\n"
    )
    ctx = custom_ctx(make_ctx, tmp_path, code)
    saved = custom.run(ctx, CustomStepArgs(description="copy the first PDF"))
    # Shown like file.save's result: "Open file" and the guide's sample output.
    assert saved == SavedFile(tmp_path / "out" / "copy.pdf")
    assert saved.path.read_bytes().startswith(b"%PDF")


def test_custom_step_returns_a_document_for_file_save(make_ctx, tmp_path):
    code = "def run(ctx):\n    return ctx.document(b'hello', 'TXT')\n"
    document = custom.run(custom_ctx(make_ctx, tmp_path, code), CustomStepArgs(description="d"))
    assert document == Document(b"hello", "txt")


def test_custom_step_is_confined_from_its_first_line(make_ctx, tmp_path):
    outside = tmp_path / "outside.txt"
    code = (
        "from pathlib import Path\n"
        f"Path({str(outside)!r}).write_text('module level')\n"
        "def run(ctx):\n    pass\n"
    )
    with pytest.raises(SandboxError):
        custom.run(custom_ctx(make_ctx, tmp_path, code), CustomStepArgs(description="d"))
    assert not outside.exists()


def test_custom_step_cannot_read_other_files(make_ctx, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("x")
    code = f"def run(ctx):\n    return ctx.read_bytes({str(secret)!r})\n"
    with pytest.raises(EngineError, match="did not select"):
        custom.run(custom_ctx(make_ctx, tmp_path, code), CustomStepArgs(description="d"))


def test_custom_step_missing_file_or_function(make_ctx, tmp_path):
    with pytest.raises(EngineError, match="missing"):
        custom.run(make_ctx(), CustomStepArgs(description="d"))
    ctx = custom_ctx(make_ctx, tmp_path, "x = 1\n")
    with pytest.raises(EngineError, match="no function run"):
        custom.run(ctx, CustomStepArgs(description="d"))


def test_indian_scripts_have_glyphs(make_ctx, invoice, caplog):
    from engine.templates.fonts import _indic_candidates

    if not any(path.is_file() for path, _ in _indic_candidates()):
        pytest.skip("no Indic font on this machine")
    items = [{"description": "किताबें", "qty": 1, "rate": 10}]
    ctx = make_ctx(inputs={**invoice.sample_inputs(), "customer_name": "श्री ट्रेडर्स", "items": items})
    ctx.outs["totals"] = calc.line_totals(ctx, TOTALS)
    with caplog.at_level("WARNING", logger="fpdf"):
        template.render_template(ctx, RenderTemplateArgs(template="invoice_basic"))
    assert "missing the following glyphs" not in caplog.text
