"""Client document folder taxonomy and rule-based classification."""

from __future__ import annotations

CLIENT_DOCUMENT_FOLDERS: list[dict[str, str]] = [
    {"key": "gst", "label": "GST"},
    {"key": "pan", "label": "PAN"},
    {"key": "proposals", "label": "Proposals"},
    {"key": "agreements", "label": "Agreements"},
    {"key": "deliverables", "label": "Deliverables"},
    {"key": "invoices", "label": "Invoices"},
    {"key": "images", "label": "Images"},
    {"key": "others", "label": "Others"},
]

VALID_FOLDER_KEYS = {f["key"] for f in CLIENT_DOCUMENT_FOLDERS}

_FOLDER_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("gst", ("gst", "gstin", "tax registration")),
    ("pan", ("pan", "permanent account")),
    ("proposals", ("proposal", "quotation", "quote", "estimate", "pitch")),
    ("agreements", ("agreement", "contract", "mou", "nda", "msa", "sow")),
    ("deliverables", ("deliverable", "final", "asset", "export", "handover")),
    ("invoices", ("invoice", "bill", "receipt", "payment")),
    ("images", (".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg")),
]


def folder_label(key: str) -> str:
    for item in CLIENT_DOCUMENT_FOLDERS:
        if item["key"] == key:
            return item["label"]
    return key.replace("_", " ").title()


def suggest_document_folder(filename: str, content_type: str = "") -> dict[str, str | float]:
    """Return suggested folder key, human label, reason, and confidence 0–1."""
    name = (filename or "").lower()
    ctype = (content_type or "").lower()

    if ctype.startswith("image/"):
        return {
            "folder": "images",
            "folder_label": folder_label("images"),
            "reason": "Image file type detected",
            "confidence": 0.95,
        }

    for folder_key, keywords in _FOLDER_RULES:
        if folder_key == "images":
            if any(name.endswith(ext) for ext in keywords):
                return {
                    "folder": "images",
                    "folder_label": folder_label("images"),
                    "reason": "Image file extension detected",
                    "confidence": 0.9,
                }
            continue
        for kw in keywords:
            if kw in name:
                return {
                    "folder": folder_key,
                    "folder_label": folder_label(folder_key),
                    "reason": f'Filename contains "{kw}"',
                    "confidence": 0.85,
                }

    return {
        "folder": "others",
        "folder_label": folder_label("others"),
        "reason": "No strong match — defaulting to Others",
        "confidence": 0.4,
    }
