"""GST invoice PDF generation using ReportLab (pure-Python, no system deps)."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ACCENT = colors.HexColor("#4f46e5")
MUTED = colors.HexColor("#64748b")
LIGHT = colors.HexColor("#eef2ff")


@dataclass
class PdfItem:
    description: str
    quantity: Decimal
    unit_price: Decimal
    amount: Decimal


@dataclass
class PdfInvoice:
    invoice_number: str
    created_on: date
    due_date: date
    status: str
    # supplier (agency)
    company_name: str
    company_email: str | None
    company_gstin: str | None
    company_address: str | None
    # customer
    client_name: str
    client_email: str | None
    client_gstin: str | None
    client_address: str | None
    place_of_supply: str | None
    # money
    items: list[PdfItem]
    subtotal: Decimal
    cgst: Decimal
    sgst: Decimal
    igst: Decimal
    tax_type: str
    total: Decimal
    currency: str
    notes: str | None


def _money(value: Decimal, currency: str) -> str:
    symbol = "Rs. " if currency == "INR" else f"{currency} "
    return f"{symbol}{Decimal(value):,.2f}"


def build_invoice_pdf(inv: PdfInvoice) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        title=f"Invoice {inv.invoice_number}",
    )

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Title"], textColor=ACCENT, fontSize=22, spaceAfter=2)
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=8.5, textColor=MUTED, leading=12)
    label = ParagraphStyle("label", parent=styles["Normal"], fontSize=8, textColor=MUTED)
    body = ParagraphStyle("body", parent=styles["Normal"], fontSize=9.5, leading=13)
    right = ParagraphStyle("right", parent=styles["Normal"], fontSize=9.5, alignment=TA_RIGHT)

    elements: list = []

    # Header: company + TAX INVOICE
    header = Table(
        [[
            Paragraph(f"<b>{inv.company_name}</b>", h1),
            Paragraph("TAX INVOICE", ParagraphStyle("ti", parent=right, fontSize=16, textColor=MUTED)),
        ]],
        colWidths=[110 * mm, 68 * mm],
    )
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    elements.append(header)

    supplier_lines = []
    if inv.company_address:
        supplier_lines.append(inv.company_address)
    if inv.company_email:
        supplier_lines.append(inv.company_email)
    if inv.company_gstin:
        supplier_lines.append(f"GSTIN: {inv.company_gstin}")
    elements.append(Paragraph("<br/>".join(supplier_lines), small))
    elements.append(Spacer(1, 8 * mm))

    # Meta: invoice number / dates / bill-to
    bill_to = [f"<b>{inv.client_name}</b>"]
    if inv.client_address:
        bill_to.append(inv.client_address)
    if inv.client_email:
        bill_to.append(inv.client_email)
    if inv.client_gstin:
        bill_to.append(f"GSTIN: {inv.client_gstin}")

    meta_right = [
        f"<b>Invoice #:</b> {inv.invoice_number}",
        f"<b>Date:</b> {inv.created_on.isoformat()}",
        f"<b>Due:</b> {inv.due_date.isoformat()}",
        f"<b>Status:</b> {inv.status.title()}",
    ]
    if inv.place_of_supply:
        meta_right.append(f"<b>Place of supply:</b> {inv.place_of_supply}")

    meta = Table(
        [[
            Paragraph("BILL TO", label),
            Paragraph("", label),
        ], [
            Paragraph("<br/>".join(bill_to), body),
            Paragraph("<br/>".join(meta_right), body),
        ]],
        colWidths=[100 * mm, 78 * mm],
    )
    meta.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, 0), 4)]))
    elements.append(meta)
    elements.append(Spacer(1, 6 * mm))

    # Line items
    rows = [["#", "Description", "Qty", "Rate", "Amount"]]
    for i, item in enumerate(inv.items, start=1):
        rows.append([
            str(i),
            Paragraph(item.description, body),
            f"{Decimal(item.quantity):g}",
            _money(item.unit_price, inv.currency),
            _money(item.amount, inv.currency),
        ])

    items_table = Table(rows, colWidths=[10 * mm, 92 * mm, 16 * mm, 30 * mm, 30 * mm], repeatRows=1)
    items_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#e2e8f0")),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(items_table)
    elements.append(Spacer(1, 4 * mm))

    # Totals
    totals_rows = [["Subtotal", _money(inv.subtotal, inv.currency)]]
    if inv.tax_type == "cgst_sgst":
        totals_rows.append(["CGST", _money(inv.cgst, inv.currency)])
        totals_rows.append(["SGST", _money(inv.sgst, inv.currency)])
    else:
        totals_rows.append(["IGST", _money(inv.igst, inv.currency)])
    totals_rows.append(["Total", _money(inv.total, inv.currency)])

    totals = Table(totals_rows, colWidths=[40 * mm, 38 * mm], hAlign="RIGHT")
    totals.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEABOVE", (0, -1), (-1, -1), 0.6, MUTED),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, -1), (-1, -1), ACCENT),
        ("FONTSIZE", (0, -1), (-1, -1), 11),
    ]))
    elements.append(totals)

    if inv.notes:
        elements.append(Spacer(1, 8 * mm))
        elements.append(Paragraph("NOTES", label))
        elements.append(Paragraph(inv.notes, small))

    elements.append(Spacer(1, 10 * mm))
    elements.append(Paragraph(
        "This is a computer-generated invoice and does not require a signature.",
        ParagraphStyle("foot", parent=small, fontSize=7.5),
    ))

    doc.build(elements)
    return buffer.getvalue()
