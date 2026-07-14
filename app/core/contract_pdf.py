"""Service agreement PDF generation."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

ACCENT = colors.HexColor("#4f46e5")
MUTED = colors.HexColor("#64748b")


@dataclass
class PdfContract:
    contract_number: str
    title: str
    agency_name: str
    client_name: str
    project_value: Decimal
    services: list[str]
    body: str
    signed_at: date | None
    signer_name: str | None
    expires_at: date | None


def _money(value: Decimal) -> str:
    return f"₹{Decimal(value):,.2f}"


def build_contract_pdf(contract: PdfContract) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        title=contract.title,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ContractTitle",
        parent=styles["Title"],
        fontSize=20,
        textColor=ACCENT,
        spaceAfter=6,
    )
    h2 = ParagraphStyle(
        "SectionHead",
        parent=styles["Heading2"],
        fontSize=12,
        textColor=ACCENT,
        spaceBefore=10,
        spaceAfter=4,
    )
    body = ParagraphStyle("Body", parent=styles["Normal"], fontSize=10, leading=14)
    muted = ParagraphStyle("Muted", parent=body, textColor=MUTED)

    story: list = []
    story.append(Paragraph("Service Agreement", title_style))
    story.append(Paragraph(contract.title, h2))
    story.append(
        Paragraph(
            f"<b>{contract.agency_name}</b> (Agency) and <b>{contract.client_name}</b> (Client)",
            muted,
        )
    )
    story.append(Paragraph(f"Agreement no. {contract.contract_number}", muted))
    story.append(Spacer(1, 8))
    story.append(Paragraph(f"Contract value: {_money(contract.project_value)}", body))
    if contract.services:
        story.append(Paragraph(f"Services: {', '.join(contract.services)}", body))
    if contract.expires_at:
        story.append(Paragraph(f"Valid until: {contract.expires_at.strftime('%d %B %Y')}", body))
    story.append(Spacer(1, 10))

    story.append(Paragraph("Terms of agreement", h2))
    for block in (contract.body or "").strip().split("\n\n"):
        for line in block.split("\n"):
            line = line.strip()
            if line:
                story.append(Paragraph(line, body))
        story.append(Spacer(1, 4))

    if contract.signed_at and contract.signer_name:
        story.append(Spacer(1, 16))
        story.append(Paragraph("Electronic signature", h2))
        story.append(
            Paragraph(
                f"Signed by <b>{contract.signer_name}</b> on "
                f"{contract.signed_at.strftime('%d %B %Y')}",
                body,
            )
        )

    doc.build(story)
    return buffer.getvalue()
