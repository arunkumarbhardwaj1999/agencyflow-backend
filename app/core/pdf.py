"""GST invoice PDF generation using ReportLab (pure-Python, no system deps)."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# Brand palette
INDIGO = colors.HexColor("#4f46e5")
INDIGO_DARK = colors.HexColor("#3730a3")
SLATE_900 = colors.HexColor("#0f172a")
SLATE_700 = colors.HexColor("#334155")
SLATE_500 = colors.HexColor("#64748b")
SLATE_200 = colors.HexColor("#e2e8f0")
SLATE_100 = colors.HexColor("#f1f5f9")
SLATE_50 = colors.HexColor("#f8fafc")
WHITE = colors.white


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
    """ReportLab Helvetica has no rupee glyph — use Rs. for INR."""
    amount = f"{Decimal(value):,.2f}"
    if currency == "INR":
        return f"Rs. {amount}"
    return f"{currency} {amount}"


def _fmt_date(d: date) -> str:
    return d.strftime("%d %b %Y")


def _status_hex(status: str) -> str:
    s = (status or "").lower()
    if s == "paid":
        return "#059669"
    if s in ("overdue", "cancelled", "void"):
        return "#e11d48"
    if s in ("sent", "unpaid", "partial"):
        return "#d97706"
    return "#64748b"


def _esc(text: str | None) -> str:
    if not text:
        return ""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def build_invoice_pdf(inv: PdfInvoice) -> bytes:
    buffer = BytesIO()
    page_w, _page_h = A4
    margin = 14 * mm
    content_w = page_w - 2 * margin

    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=12 * mm,
        bottomMargin=14 * mm,
        leftMargin=margin,
        rightMargin=margin,
        title=f"Invoice {inv.invoice_number}",
    )

    styles = getSampleStyleSheet()
    company_name = ParagraphStyle(
        "CompanyName",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=18,
        textColor=INDIGO_DARK,
        leading=22,
        spaceAfter=2,
    )
    doc_title = ParagraphStyle(
        "DocTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=18,
        textColor=SLATE_900,
        alignment=TA_RIGHT,
        leading=22,
    )
    muted = ParagraphStyle(
        "Muted",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        textColor=SLATE_500,
        leading=12,
    )
    muted_right = ParagraphStyle("MutedRight", parent=muted, alignment=TA_RIGHT)
    section_label = ParagraphStyle(
        "SectionLabel",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        textColor=SLATE_500,
        leading=10,
        spaceAfter=4,
    )
    body = ParagraphStyle(
        "Body",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9.5,
        textColor=SLATE_900,
        leading=13,
    )
    body_bold = ParagraphStyle("BodyBold", parent=body, fontName="Helvetica-Bold")
    cell = ParagraphStyle(
        "Cell",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        textColor=SLATE_700,
        leading=12,
    )
    cell_right = ParagraphStyle("CellRight", parent=cell, alignment=TA_RIGHT)
    cell_center = ParagraphStyle("CellCenter", parent=cell, alignment=TA_CENTER)
    th = ParagraphStyle(
        "TH",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8.5,
        textColor=WHITE,
        leading=11,
    )
    th_right = ParagraphStyle("THRight", parent=th, alignment=TA_RIGHT)
    th_center = ParagraphStyle("THCenter", parent=th, alignment=TA_CENTER)
    total_label = ParagraphStyle(
        "TotalLabel",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=11,
        textColor=WHITE,
        alignment=TA_LEFT,
    )
    total_value = ParagraphStyle(
        "TotalValue",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=11,
        textColor=WHITE,
        alignment=TA_RIGHT,
    )
    footer = ParagraphStyle(
        "Footer",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7.5,
        textColor=SLATE_500,
        alignment=TA_CENTER,
        leading=10,
    )

    elements: list = []

    # Top brand bar
    bar = Table([[""]], colWidths=[content_w], rowHeights=[3.2 * mm])
    bar.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), INDIGO),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    elements.append(bar)
    elements.append(Spacer(1, 7 * mm))

    # Header: agency | TAX INVOICE
    supplier_bits = []
    if inv.company_address:
        supplier_bits.append(_esc(inv.company_address))
    if inv.company_email:
        supplier_bits.append(_esc(inv.company_email))
    if inv.company_gstin:
        supplier_bits.append(f"GSTIN: {_esc(inv.company_gstin)}")
    supplier_html = "<br/>".join(supplier_bits) if supplier_bits else "&nbsp;"

    status_label = (inv.status or "draft").replace("_", " ").title()
    header = Table(
        [[
            [
                Paragraph(_esc(inv.company_name) or "Agency", company_name),
                Paragraph(supplier_html, muted),
            ],
            [
                Paragraph("TAX INVOICE", doc_title),
                Paragraph(
                    f'<font color="{_status_hex(inv.status)}">'
                    f"<b>Status: {status_label}</b></font>",
                    muted_right,
                ),
            ],
        ]],
        colWidths=[content_w * 0.58, content_w * 0.42],
    )
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    elements.append(header)
    elements.append(Spacer(1, 5 * mm))
    elements.append(HRFlowable(width="100%", thickness=0.6, color=SLATE_200, spaceBefore=0, spaceAfter=5 * mm))

    # Bill to + invoice meta cards
    bill_lines = [f"<b>{_esc(inv.client_name)}</b>"]
    if inv.client_address:
        bill_lines.append(_esc(inv.client_address))
    if inv.client_email:
        bill_lines.append(_esc(inv.client_email))
    if inv.client_gstin:
        bill_lines.append(f"GSTIN: {_esc(inv.client_gstin)}")

    meta_lines = [
        f"<b>Invoice #</b>&nbsp;&nbsp;{_esc(inv.invoice_number)}",
        f"<b>Invoice date</b>&nbsp;&nbsp;{_fmt_date(inv.created_on)}",
        f"<b>Due date</b>&nbsp;&nbsp;{_fmt_date(inv.due_date)}",
    ]
    if inv.place_of_supply:
        meta_lines.append(f"<b>Place of supply</b>&nbsp;&nbsp;{_esc(inv.place_of_supply)}")

    left_card = Table(
        [[
            Paragraph("BILL TO", section_label),
        ], [
            Paragraph("<br/>".join(bill_lines), body),
        ]],
        colWidths=[content_w * 0.48],
    )
    left_card.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), SLATE_50),
        ("BOX", (0, 0), (-1, -1), 0.6, SLATE_200),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (0, 0), 8),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 8),
        ("TOPPADDING", (0, 1), (-1, 1), 2),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))

    right_card = Table(
        [[
            Paragraph("INVOICE DETAILS", section_label),
        ], [
            Paragraph("<br/>".join(meta_lines), body),
        ]],
        colWidths=[content_w * 0.48],
    )
    right_card.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), SLATE_50),
        ("BOX", (0, 0), (-1, -1), 0.6, SLATE_200),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (0, 0), 8),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 8),
        ("TOPPADDING", (0, 1), (-1, 1), 2),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))

    cards = Table(
        [[left_card, right_card]],
        colWidths=[content_w * 0.5, content_w * 0.5],
    )
    cards.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (0, 0), 0),
        ("RIGHTPADDING", (0, 0), (0, 0), 3 * mm),
        ("LEFTPADDING", (1, 0), (1, 0), 3 * mm),
        ("RIGHTPADDING", (1, 0), (1, 0), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    elements.append(cards)
    elements.append(Spacer(1, 7 * mm))

    # Line items
    col_w = [
        content_w * 0.07,
        content_w * 0.45,
        content_w * 0.12,
        content_w * 0.18,
        content_w * 0.18,
    ]
    rows: list = [[
        Paragraph("#", th_center),
        Paragraph("Description", th),
        Paragraph("Qty", th_right),
        Paragraph("Rate", th_right),
        Paragraph("Amount", th_right),
    ]]
    for i, item in enumerate(inv.items, start=1):
        rows.append([
            Paragraph(str(i), cell_center),
            Paragraph(_esc(item.description) or "—", cell),
            Paragraph(f"{Decimal(item.quantity):g}", cell_right),
            Paragraph(_money(item.unit_price, inv.currency), cell_right),
            Paragraph(_money(item.amount, inv.currency), cell_right),
        ])

    items_table = Table(rows, colWidths=col_w, repeatRows=1)
    items_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), INDIGO),
        ("BACKGROUND", (0, 1), (-1, -1), WHITE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, SLATE_50]),
        ("BOX", (0, 0), (-1, -1), 0.7, INDIGO),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, SLATE_200),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, 0), 8),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
        ("TOPPADDING", (0, 1), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(items_table)
    elements.append(Spacer(1, 5 * mm))

    # Totals (right-aligned card)
    tax_rows: list[list] = [
        [Paragraph("Subtotal", cell), Paragraph(_money(inv.subtotal, inv.currency), cell_right)],
    ]
    if inv.tax_type == "cgst_sgst":
        tax_rows.append([Paragraph("CGST", cell), Paragraph(_money(inv.cgst, inv.currency), cell_right)])
        tax_rows.append([Paragraph("SGST", cell), Paragraph(_money(inv.sgst, inv.currency), cell_right)])
    else:
        tax_rows.append([Paragraph("IGST", cell), Paragraph(_money(inv.igst, inv.currency), cell_right)])

    tax_table = Table(tax_rows, colWidths=[42 * mm, 40 * mm])
    tax_table.setStyle(TableStyle([
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("LINEBELOW", (0, -1), (-1, -1), 0.5, SLATE_200),
    ]))

    total_table = Table(
        [[
            Paragraph("TOTAL PAYABLE", total_label),
            Paragraph(_money(inv.total, inv.currency), total_value),
        ]],
        colWidths=[42 * mm, 40 * mm],
    )
    total_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), INDIGO),
        ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))

    totals_block = Table(
        [[tax_table], [total_table]],
        colWidths=[82 * mm],
    )
    totals_block.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, SLATE_200),
        ("BACKGROUND", (0, 0), (-1, 0), SLATE_50),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))

    totals_wrap = Table(
        [[Paragraph("", body), totals_block]],
        colWidths=[content_w - 82 * mm, 82 * mm],
    )
    totals_wrap.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    elements.append(KeepTogether([totals_wrap]))

    if inv.notes:
        elements.append(Spacer(1, 7 * mm))
        notes_box = Table(
            [[
                Paragraph("NOTES", section_label),
            ], [
                Paragraph(_esc(inv.notes), muted),
            ]],
            colWidths=[content_w],
        )
        notes_box.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), SLATE_50),
            ("BOX", (0, 0), (-1, -1), 0.6, SLATE_200),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (0, 0), 8),
            ("BOTTOMPADDING", (0, -1), (-1, -1), 8),
            ("TOPPADDING", (0, 1), (-1, 1), 2),
        ]))
        elements.append(notes_box)

    elements.append(Spacer(1, 10 * mm))
    elements.append(HRFlowable(width="100%", thickness=0.5, color=SLATE_200, spaceBefore=0, spaceAfter=3 * mm))
    elements.append(
        Paragraph(
            "This is a computer-generated tax invoice and does not require a physical signature.",
            footer,
        )
    )
    elements.append(
        Paragraph(
            f"{_esc(inv.company_name)} · {_esc(inv.invoice_number)}",
            footer,
        )
    )

    doc.build(elements)
    return buffer.getvalue()
