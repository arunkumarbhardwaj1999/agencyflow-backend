"""Rule-based deal insights — no external AI API required."""

from __future__ import annotations

from datetime import UTC, date, datetime

from app.models.deal import Deal
from app.models.deal_activity import DealActivity
from app.models.deal_email import DealEmail
from app.schemas.deal import STAGE_DEFAULT_PROBABILITY, DealInsights


def _confidence_label(probability: int) -> str:
    if probability >= 75:
        return "High"
    if probability >= 45:
        return "Medium"
    return "Low"


def compute_deal_insights(
    deal: Deal,
    *,
    recent_activities: list[DealActivity],
    recent_emails: list[DealEmail],
) -> DealInsights:
    base = STAGE_DEFAULT_PROBABILITY.get(deal.status, deal.probability or 50)
    probability = deal.probability if deal.probability is not None else base

    completed = [a for a in recent_activities if a.is_completed]
    upcoming = [a for a in recent_activities if not a.is_completed]
    opened_emails = [e for e in recent_emails if e.open_status == "opened"]

    recommendations: list[str] = []
    summary_parts: list[str] = []

    if deal.status == "qualification":
        recommendations.append("Schedule a discovery call to qualify budget and timeline.")
    elif deal.status == "proposal_sent":
        recommendations.append("Follow up within 2 days to confirm the proposal was received.")
        if opened_emails:
            summary_parts.append(f"Client has opened the proposal {len(opened_emails)} time(s).")
    elif deal.status == "negotiation":
        recommendations.append("Address objections and send a revised quotation if needed.")
        probability = max(probability, 70)

    if deal.expected_close_date:
        days_left = (deal.expected_close_date - date.today()).days
        if days_left < 0:
            recommendations.append("Expected close date has passed — update the close date or stage.")
            probability = max(0, probability - 15)
        elif days_left <= 7:
            recommendations.append("Close date is within a week — prioritize follow-up.")
            probability = min(100, probability + 5)

    if completed:
        summary_parts.append(f"{len(completed)} recent activity(ies) logged.")
    if upcoming:
        recommendations.append("Complete scheduled follow-ups to keep momentum.")

    if not recent_emails and deal.status in {"proposal_sent", "negotiation"}:
        recommendations.append("Send a follow-up email with the latest proposal or meeting notes.")

    if deal.status == "won":
        probability = 100
        summary_parts.append("Deal is won — client conversion should be complete.")
    elif deal.status == "lost":
        probability = 0
        summary_parts.append("Deal marked as lost.")

    if not summary_parts:
        summary_parts.append("Likely to convert." if probability >= 60 else "Needs more engagement.")

    return DealInsights(
        probability=probability,
        confidence=_confidence_label(probability),
        summary=" ".join(summary_parts),
        recommendations=recommendations[:3],
    )
