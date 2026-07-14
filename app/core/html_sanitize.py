"""Minimal HTML sanitization for lead note rich text."""

import re

_ALLOWED_TAGS = ("p", "br", "b", "strong", "i", "em", "u", "ul", "ol", "li", "div", "span")
_TAG_RE = re.compile(r"<(/?)([a-zA-Z0-9]+)([^>]*)>", re.IGNORECASE)


def sanitize_note_html(content: str) -> str:
    text = content.strip()
    if not text:
        return text
    if "<" not in text:
        return text

    def _replace(match: re.Match[str]) -> str:
        closing, tag, _rest = match.group(1), match.group(2).lower(), match.group(3)
        if tag not in _ALLOWED_TAGS:
            return ""
        return f"<{closing}{tag}>"

    cleaned = _TAG_RE.sub(_replace, text)
    cleaned = re.sub(r"<script[^>]*>.*?</script>", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"on\w+\s*=\s*['\"][^'\"]*['\"]", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()
