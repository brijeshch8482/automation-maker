"""invoice_basic: a one-page A4 GST invoice.

Reads, by name: settings business_name, gstin, logo; inputs customer_name, customer_phone and
the table used by calc.line_totals; outs invoice_no and the calc.line_totals result.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

from fpdf import FPDF

from engine.context import RunContext
from engine.errors import EngineError
from engine.money import format_indian, format_number
from engine.templates.fonts import latin1, setup_font

INK = (31, 41, 55)
MUTED = (100, 116, 139)
ACCENT = (79, 70, 229)
RULE = (226, 232, 240)


def _totals(ctx: RunContext) -> dict[str, Any]:
    for value in ctx.outs.values():
        if isinstance(value, dict) and {"rows", "subtotal", "total"} <= value.keys():
            return value
    raise EngineError("invoice_basic needs a calc.line_totals step before it")


def _description_key(row: dict[str, Any]) -> str | None:
    if "description" in row:
        return "description"
    return next((k for k, v in row.items() if isinstance(v, str) and k != "amount"), None)


def render_invoice(ctx: RunContext) -> bytes:
    totals = _totals(ctx)
    s, i = ctx.settings, ctx.inputs
    invoice_no = str(ctx.outs.get("invoice_no") or "")

    pdf = FPDF(format="A4", unit="mm")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(18, 18, 18)
    pdf.set_creator("MakeMyEXE")
    pdf.set_title(f"Invoice {invoice_no}".strip())
    pdf.add_page()
    font = setup_font(pdf)
    t = lambda text: latin1(str(text), font)  # noqa: E731
    money = lambda value: f"{font.rupee} {format_indian(Decimal(value))}"  # noqa: E731
    width = pdf.w - pdf.l_margin - pdf.r_margin

    # Header: logo + business on the left, invoice details on the right.
    top = pdf.get_y()
    left_x = pdf.l_margin
    logo = s.get("logo")
    if logo and Path(logo).is_file():
        try:
            pdf.image(str(logo), x=left_x, y=top, h=18)
            left_x += 24
        except Exception:  # an unreadable logo shouldn't stop the invoice
            pass
    pdf.set_xy(left_x, top)
    pdf.set_font(font.family, "B", 16)
    pdf.set_text_color(*INK)
    pdf.cell(
        width * 0.6 - (left_x - pdf.l_margin),
        8,
        t(s.get("business_name") or ""),
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.set_x(left_x)
    pdf.set_font(font.family, "", 9)
    pdf.set_text_color(*MUTED)
    if s.get("gstin"):
        pdf.cell(80, 5, t(f"GSTIN: {s['gstin']}"), new_x="LMARGIN", new_y="NEXT")

    pdf.set_xy(pdf.l_margin + width * 0.6, top)
    pdf.set_font(font.family, "B", 14)
    pdf.set_text_color(*ACCENT)
    pdf.cell(width * 0.4, 8, "TAX INVOICE", align="R", new_x="LEFT", new_y="NEXT")
    pdf.set_font(font.family, "", 9)
    pdf.set_text_color(*INK)
    for label, value in (("Invoice no.", invoice_no), ("Date", ctx.today.strftime("%d-%m-%Y"))):
        pdf.cell(width * 0.4, 5, t(f"{label}  {value}"), align="R", new_x="LEFT", new_y="NEXT")

    # Bill to
    pdf.set_y(max(pdf.get_y(), top + 22) + 6)
    pdf.set_draw_color(*RULE)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + width, pdf.get_y())
    pdf.ln(4)
    pdf.set_font(font.family, "", 8)
    pdf.set_text_color(*MUTED)
    pdf.cell(width, 4, "BILL TO", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(font.family, "B", 11)
    pdf.set_text_color(*INK)
    pdf.cell(width, 6, t(i.get("customer_name") or ""), new_x="LMARGIN", new_y="NEXT")
    if i.get("customer_phone"):
        pdf.set_font(font.family, "", 9)
        pdf.cell(width, 5, t(i["customer_phone"]), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)

    # Items table
    cols = [
        ("#", 0.06, "L"),
        ("Description", 0.48, "L"),
        ("Qty", 0.12, "R"),
        ("Rate", 0.16, "R"),
        ("Amount", 0.18, "R"),
    ]
    pdf.set_fill_color(241, 245, 249)
    pdf.set_font(font.family, "B", 9)
    for label, share, align in cols:
        pdf.cell(width * share, 8, label, align=align, fill=True)
    pdf.ln()
    pdf.set_font(font.family, "", 9)
    for n, row in enumerate(totals["rows"], start=1):
        key = _description_key(row)
        cells = [
            str(n),
            t(row.get(key, "") if key else ""),
            format_number(row["qty"]) if "qty" in row else "",
            format_indian(row["rate"]) if "rate" in row else "",
            format_indian(row["amount"]),
        ]
        for (_, share, align), text in zip(cols, cells, strict=True):
            pdf.cell(width * share, 7, text, align=align)
        pdf.ln()
        pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + width, pdf.get_y())

    # Totals
    pdf.ln(3)
    label_w, value_w = width * 0.3, width * 0.2
    x = pdf.l_margin + width - label_w - value_w
    lines = [("Subtotal", money(totals["subtotal"]), False)]
    if totals["tax_percent"]:
        lines.append((f"GST {format_number(totals['tax_percent'])}%", money(totals["tax"]), False))
    lines.append(("Total", money(totals["total"]), True))
    for label, value, bold in lines:
        pdf.set_x(x)
        pdf.set_font(font.family, "B" if bold else "", 11 if bold else 9)
        pdf.cell(label_w, 7, label, align="R")
        pdf.cell(value_w, 7, value, align="R", new_x="LMARGIN", new_y="NEXT")

    pdf.set_y(-22)
    pdf.set_font(font.family, "", 7)
    pdf.set_text_color(*MUTED)
    pdf.cell(width, 4, "Made on this PC with MakeMyEXE. Works offline.", align="C")
    return bytes(pdf.output())
