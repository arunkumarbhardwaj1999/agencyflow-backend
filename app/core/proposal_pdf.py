"""Branded proposal PDF generation."""

from dataclasses import dataclass
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
class PdfProposal:
    title: str
    agency_name: str
    client_name: str
    template_label: str
    project_value: Decimal
    services: list[str]
    sections: list[tuple[str, str]]


def _money(value: Decimal) -> str:
    return f"₹{Decimal(value):,.2f}"


def build_proposal_pdf(proposal: PdfProposal) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        title=proposal.title,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ProposalTitle",
        parent=styles["Title"],
        fontSize=22,
        textColor=ACCENT,
        spaceAfter=8,
    )
    h2 = ParagraphStyle(
        "SectionHead",
        parent=styles["Heading2"],
        fontSize=13,
        textColor=ACCENT,
        spaceBefore=12,
        spaceAfter=6,
    )
    body = ParagraphStyle("Body", parent=styles["Normal"], fontSize=10, leading=14)
    muted = ParagraphStyle("Muted", parent=body, textColor=MUTED)

    story: list = []
    story.append(Paragraph(proposal.title, title_style))
    story.append(
        Paragraph(
            f"<b>{proposal.agency_name}</b> · Prepared for <b>{proposal.client_name}</b>",
            muted,
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        Paragraph(
            f"Template: {proposal.template_label} · Project value: {_money(proposal.project_value)}",
            muted,
        )
    )
    if proposal.services:
        story.append(Paragraph(f"Services: {', '.join(proposal.services)}", muted))
    story.append(Spacer(1, 10))

    for heading, text in proposal.sections:
        if not (text or "").strip():
            continue
        story.append(Paragraph(heading, h2))
        for block in text.strip().split("\n\n"):
            for line in block.split("\n"):
                line = line.strip()
                if not line:
                    continue
                if line.startswith("- ") or line.startswith("• "):
                    story.append(Paragraph(line, body))
                else:
                    story.append(Paragraph(line, body))
            story.append(Spacer(1, 4))

    doc.build(story)
    return buffer.getvalue()
