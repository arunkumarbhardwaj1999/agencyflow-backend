"""Format seconds as human-readable duration labels."""

from __future__ import annotations


def format_duration(seconds: int) -> str:
    if seconds < 0:
        seconds = 0
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours}h {minutes}m"
    if minutes > 0:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def format_duration_clock(seconds: int) -> str:
    if seconds < 0:
        seconds = 0
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def format_hours_decimal(seconds: int) -> float:
    return round(seconds / 3600, 2)
