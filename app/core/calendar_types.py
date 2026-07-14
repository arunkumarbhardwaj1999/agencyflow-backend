"""Unified calendar event types, colors, and icons."""

from __future__ import annotations

EVENT_COLORS = {
    "meeting": "#3B82F6",
    "call": "#22C55E",
    "task": "#F97316",
    "follow_up": "#F59E0B",
    "proposal": "#FB923C",
    "project_deadline": "#EF4444",
    "invoice_due": "#A855F7",
    "contract_expiry": "#DC2626",
    "lead_followup": "#F59E0B",
    "deal_close": "#EF4444",
    "demo": "#3B82F6",
    "email": "#22C55E",
}

EVENT_ICONS = {
    "meeting": "calendar-meeting",
    "call": "phone",
    "task": "check-square",
    "follow_up": "clock",
    "proposal": "file-text",
    "project_deadline": "flag",
    "invoice_due": "receipt",
    "contract_expiry": "file-signature",
    "lead_followup": "user-clock",
    "deal_close": "target",
    "demo": "presentation",
    "email": "mail",
}

ACTIVITY_TYPE_MAP = {
    "call": "call",
    "meeting": "meeting",
    "follow_up": "follow_up",
    "task": "task",
    "demo": "demo",
    "proposal": "proposal",
    "email": "email",
}


def calendar_color(event_type: str) -> str:
    return EVENT_COLORS.get(event_type, "#64748B")


def calendar_icon(event_type: str) -> str:
    return EVENT_ICONS.get(event_type, "calendar")
