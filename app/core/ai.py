"""AI helpers powered by Anthropic Claude.

When ANTHROPIC_API_KEY is not set, returns deterministic mock drafts built from
CRM context so features can be tested without an API account.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator

import httpx

from app.core.config import get_settings

logger = logging.getLogger("agencyflow.ai")
settings = get_settings()

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"


class AIError(Exception):
    pass


async def complete(system: str, user_prompt: str, max_tokens: int = 1024) -> str:
    if not settings.ai_enabled:
        return _mock_complete(user_prompt)

    payload = {
        "model": settings.anthropic_model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user_prompt}],
    }
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                ANTHROPIC_URL,
                headers={
                    "x-api-key": settings.anthropic_api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=payload,
                timeout=60.0,
            )
        if resp.status_code >= 400:
            logger.warning("Claude API error (%s): %s", resp.status_code, resp.text[:300])
            raise AIError("AI service returned an error")
        data = resp.json()
        blocks = data.get("content", [])
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        return text.strip() or "No response generated."
    except AIError:
        raise
    except Exception as exc:
        logger.warning("Claude request failed: %s", exc)
        raise AIError("AI service unavailable") from exc


async def stream_complete(
    system: str, user_prompt: str, max_tokens: int = 1024
) -> AsyncIterator[str]:
    """Yield text chunks. Mock mode simulates streaming by word batches."""
    if not settings.ai_enabled:
        text = _mock_complete(user_prompt)
        words = text.split(" ")
        chunk = ""
        for i, word in enumerate(words):
            chunk += (" " if i else "") + word
            if len(chunk) > 40 or i == len(words) - 1:
                yield chunk
                chunk = ""
        return

    payload = {
        "model": settings.anthropic_model,
        "max_tokens": max_tokens,
        "stream": True,
        "system": system,
        "messages": [{"role": "user", "content": user_prompt}],
    }
    try:
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                ANTHROPIC_URL,
                headers={
                    "x-api-key": settings.anthropic_api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=payload,
                timeout=90.0,
            ) as resp:
                if resp.status_code >= 400:
                    body = await resp.aread()
                    logger.warning("Claude stream error (%s): %s", resp.status_code, body[:300])
                    raise AIError("AI service returned an error")
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    raw = line[6:].strip()
                    if raw == "[DONE]":
                        break
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if event.get("type") == "content_block_delta":
                        delta = event.get("delta", {})
                        text = delta.get("text", "")
                        if text:
                            yield text
    except AIError:
        raise
    except Exception as exc:
        logger.warning("Claude stream failed: %s", exc)
        raise AIError("AI service unavailable") from exc


def _mock_complete(prompt: str) -> str:
    lower = prompt.lower()
    if "invoice" in lower and "email" in lower:
        return (
            "Subject: Invoice {invoice_number} from {agency}\n\n"
            "Hi {client},\n\n"
            "Please find attached invoice {invoice_number} for ₹{amount}, due on {due_date}. "
            "You can pay online using the link in the email or reply if you need any changes.\n\n"
            "Thank you for your business!\n\n"
            "Best regards,\n{agency}"
        )
    if "task" in lower and ("polish" in lower or "description" in lower):
        return (
            "Deliver a polished homepage redesign including responsive layouts, "
            "brand-aligned colour palette, and two rounds of client revisions. "
            "Target launch within the agreed sprint window."
        )
    if "welcome" in lower or "onboarding" in lower:
        return (
            "Subject: Welcome to {agency} — your client portal is ready\n\n"
            "Hi {client},\n\n"
            "We're excited to partner with you! Your dedicated client portal is now live. "
            "You can track project progress, view invoices, and message our team anytime.\n\n"
            "We'll be in touch shortly to kick off your first milestone.\n\n"
            "Warm regards,\n{agency}"
        )
    if "draft" in lower or "email" in lower:
        return (
            "Subject: Following up on your enquiry\n\n"
            "Hi there,\n\n"
            "Thank you for reaching out to us. I wanted to follow up and see if you had "
            "any questions about how we can help with your project.\n\n"
            "Happy to jump on a quick call this week if that works for you.\n\n"
            "Best regards,\nYour Agency Team"
        )
    if "summarize" in lower or "project" in lower:
        return (
            "**Project summary (mock)**\n\n"
            "- Status: In progress with active tasks on the board.\n"
            "- Next steps: Complete pending deliverables and schedule a client review.\n"
            "- Risk: Monitor deadlines on open tasks.\n\n"
            "_Connect ANTHROPIC_API_KEY for live AI summaries._"
        )
    if "follow" in lower:
        return (
            "- Lead with overdue follow-up — send a check-in today.\n"
            "- Proposal-stage leads — confirm decision timeline.\n"
            "- New leads from this week — send intro email within 24h."
        )
    return "AI mock response — set ANTHROPIC_API_KEY for live Claude output."


async def draft_lead_email(
    *,
    lead_name: str,
    company_name: str | None,
    status: str,
    value: str,
    notes: str | None,
    agency_name: str,
) -> str:
    system = (
        "You are a professional copywriter for an Indian digital agency. "
        "Write concise, warm client emails. Use INR when mentioning money."
    )
    prompt = (
        f"Draft a short follow-up email to a sales lead.\n\n"
        f"Agency: {agency_name}\n"
        f"Lead name: {lead_name}\n"
        f"Company: {company_name or 'N/A'}\n"
        f"Pipeline stage: {status}\n"
        f"Deal value: ₹{value}\n"
        f"Notes: {notes or 'None'}\n\n"
        f"Include a subject line. Keep it under 150 words."
    )
    return await complete(system, prompt)


async def draft_invoice_email(
    *,
    client_name: str,
    invoice_number: str,
    amount: str,
    due_date: str,
    agency_name: str,
) -> str:
    system = (
        "You write professional invoice emails for an Indian digital agency. "
        "Be clear about amount, due date, and payment. Use ₹ for INR."
    )
    prompt = (
        f"Draft an email to send an invoice to a client.\n\n"
        f"Agency: {agency_name}\n"
        f"Client: {client_name}\n"
        f"Invoice: {invoice_number}\n"
        f"Amount: ₹{amount}\n"
        f"Due date: {due_date}\n\n"
        f"Include subject line. Mention PDF attachment and online payment. Under 120 words."
    )
    return await complete(system, prompt)


async def polish_task_description(
    *,
    title: str,
    description: str | None,
    project_title: str,
) -> str:
    system = "You improve task descriptions for agency project management. Be specific and actionable."
    prompt = (
        f"Polish this task description for clarity:\n\n"
        f"Project: {project_title}\n"
        f"Task: {title}\n"
        f"Current description: {description or 'None'}\n\n"
        f"Return only the improved description (2–4 sentences)."
    )
    return await complete(system, prompt, max_tokens=512)


async def draft_client_welcome(
    *,
    client_name: str,
    agency_name: str,
    project_title: str | None,
) -> str:
    system = (
        "You write warm onboarding emails for new agency clients in India. "
        "Mention the client portal and next steps."
    )
    prompt = (
        f"Draft a welcome email for a new client.\n\n"
        f"Agency: {agency_name}\n"
        f"Client: {client_name}\n"
        f"First project: {project_title or 'To be confirmed'}\n\n"
        f"Include subject line. Under 130 words."
    )
    return await complete(system, prompt)


async def summarize_project(
    *,
    title: str,
    status: str,
    budget: str,
    task_total: int,
    task_done: int,
    client_name: str,
    description: str | None,
) -> str:
    system = "You summarize agency project status for internal standups. Use bullet points."
    prompt = (
        f"Summarize this project for the team:\n\n"
        f"Project: {title}\n"
        f"Client: {client_name}\n"
        f"Status: {status}\n"
        f"Budget: ₹{budget}\n"
        f"Tasks: {task_done}/{task_total} done\n"
        f"Description: {description or 'N/A'}\n\n"
        f"Highlight progress, blockers, and suggested next actions."
    )
    return await complete(system, prompt)


async def suggest_followups(
    *,
    leads_summary: list[dict],
    agency_name: str,
) -> str:
    system = "You are a sales coach for a digital agency CRM. Be specific and actionable."
    lines = "\n".join(
        f"- {l['name']} ({l['status']}), value ₹{l['value']}, follow-up: {l.get('followup', 'none')}"
        for l in leads_summary[:15]
    )
    prompt = (
        f"Agency: {agency_name}\n\n"
        f"Open leads:\n{lines or 'No open leads.'}\n\n"
        f"Suggest 3–5 follow-up actions for today, prioritizing overdue follow-ups."
    )
    return await complete(system, prompt)
