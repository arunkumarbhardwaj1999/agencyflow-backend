"""Execute workflow automations for CRM events."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.email import send_custom_email
from app.models.automation import Automation, AutomationRun
from app.models.client import Client
from app.models.invoice import Invoice
from app.models.lead import Lead
from app.models.project import Project
from app.models.role import Role
from app.models.task import Task
from app.models.user import User
from app.services.whatsapp_service import enqueue_whatsapp, persist_log

logger = logging.getLogger("agencyflow.automations")


async def fire_trigger(
    db: AsyncSession,
    *,
    company_id: UUID,
    trigger_key: str,
    entity_type: str | None = None,
    entity_id: UUID | None = None,
    context: dict[str, Any] | None = None,
) -> int:
    """Run all active automations for a trigger. Returns number of workflows executed."""
    result = await db.execute(
        select(Automation).where(
            Automation.company_id == company_id,
            Automation.trigger_key == trigger_key,
            Automation.is_active.is_(True),
        )
    )
    automations = list(result.scalars().all())
    if not automations:
        return 0

    ctx = dict(context or {})
    ctx.setdefault("company_id", str(company_id))
    ctx.setdefault("entity_type", entity_type)
    ctx.setdefault("entity_id", str(entity_id) if entity_id else None)

    ran = 0
    for automation in automations:
        try:
            action_results = await _run_actions(db, automation, ctx)
            db.add(
                AutomationRun(
                    company_id=company_id,
                    automation_id=automation.id,
                    trigger_key=trigger_key,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    status="completed",
                    result={"actions": action_results},
                )
            )
            ran += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("Automation %s failed: %s", automation.id, exc)
            db.add(
                AutomationRun(
                    company_id=company_id,
                    automation_id=automation.id,
                    trigger_key=trigger_key,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    status="failed",
                    result={"error": str(exc)},
                )
            )
    await db.flush()
    return ran


async def _run_actions(db: AsyncSession, automation: Automation, ctx: dict[str, Any]) -> list[dict]:
    results: list[dict] = []
    for action in automation.actions or []:
        action_type = action.get("type") if isinstance(action, dict) else None
        config = action.get("config", {}) if isinstance(action, dict) else {}
        if not action_type:
            continue
        try:
            detail = await _execute_action(db, action_type, config, ctx)
            results.append({"type": action_type, "status": "ok", "detail": detail})
        except Exception as exc:  # noqa: BLE001
            results.append({"type": action_type, "status": "error", "detail": str(exc)})
    return results


async def _execute_action(
    db: AsyncSession,
    action_type: str,
    config: dict,
    ctx: dict[str, Any],
) -> str:
    company_id = UUID(ctx["company_id"])

    if action_type == "wait":
        days = int(config.get("days") or 2)
        return f"Wait {days} day(s) scheduled (logged)"

    if action_type == "assign_manager":
        return await _assign_manager(db, company_id, ctx, config)

    if action_type == "send_email":
        return await _send_email_action(db, ctx, config)

    if action_type == "send_whatsapp":
        return await _send_whatsapp_action(db, company_id, ctx, config)

    if action_type == "create_task":
        return await _create_task_action(db, company_id, ctx, config)

    if action_type == "update_status":
        return await _update_status_action(db, company_id, ctx, config)

    if action_type == "notify_manager":
        return await _notify_role(db, company_id, "manager", ctx, config)

    if action_type == "notify_owner":
        return await _notify_role(db, company_id, "owner", ctx, config)

    if action_type == "webhook":
        return await _call_webhook(config, ctx)

    return f"Unknown action: {action_type}"


async def _assign_manager(db: AsyncSession, company_id: UUID, ctx: dict, config: dict) -> str:
    manager_id = config.get("user_id")
    manager = None
    if manager_id:
        manager = await db.get(User, UUID(str(manager_id)))
    if not manager:
        result = await db.execute(
            select(User)
            .options(selectinload(User.role))
            .where(User.company_id == company_id, User.is_active.is_(True))
        )
        for user in result.scalars().all():
            if user.role and user.role.name in ("manager", "owner"):
                manager = user
                break
    if not manager:
        return "No manager found"

    entity_type = ctx.get("entity_type")
    entity_id = ctx.get("entity_id")
    if entity_type == "lead" and entity_id:
        lead = await db.get(Lead, UUID(str(entity_id)))
        if lead and lead.company_id == company_id:
            lead.assigned_user_id = manager.id
            await db.flush()
            return f"Lead assigned to {manager.first_name}"
    return f"Assigned target: {manager.first_name}"


async def _send_email_action(db: AsyncSession, ctx: dict, config: dict) -> str:
    to = config.get("to") or ctx.get("email")
    if not to and ctx.get("entity_type") == "lead" and ctx.get("entity_id"):
        lead = await db.get(Lead, UUID(str(ctx["entity_id"])))
        to = lead.email if lead else None
    if not to and ctx.get("entity_type") == "invoice" and ctx.get("entity_id"):
        invoice = await db.get(Invoice, UUID(str(ctx["entity_id"])))
        if invoice:
            client = await db.get(Client, invoice.client_id)
            to = client.email if client else None
    if not to:
        return "No email recipient"
    subject = config.get("subject") or "Update from AgencyFlow"
    body = config.get("body") or f"Automation triggered: {ctx.get('trigger_key', 'event')}"
    sent, err = await send_custom_email(to, subject, body)
    return f"Email to {to}" if sent else f"Email logged/failed: {err or 'mock'}"


async def _send_whatsapp_action(db: AsyncSession, company_id: UUID, ctx: dict, config: dict) -> str:
    phone = config.get("phone") or ctx.get("phone")
    name = ctx.get("name") or "there"
    if not phone and ctx.get("entity_type") == "lead" and ctx.get("entity_id"):
        lead = await db.get(Lead, UUID(str(ctx["entity_id"])))
        if lead:
            phone = lead.phone
            name = lead.name
    if not phone:
        return "No phone number"
    message = config.get("message") or f"Hello {name}, thanks for connecting with us!"
    enqueue_whatsapp(
        company_id=company_id,
        client_id=None,
        phone=phone,
        message=message,
        template_key=None,
        use_template=False,
    )
    await persist_log(
        db,
        company_id=company_id,
        client_id=None,
        phone=phone,
        message=message,
        status="queued",
        template_key="automation",
    )
    return f"WhatsApp queued to {phone}"


async def _create_task_action(db: AsyncSession, company_id: UUID, ctx: dict, config: dict) -> str:
    project_id = config.get("project_id") or ctx.get("project_id")
    if not project_id and ctx.get("entity_type") == "project" and ctx.get("entity_id"):
        project_id = ctx["entity_id"]
    if not project_id:
        # attach to first active project if available
        result = await db.execute(
            select(Project).where(
                Project.company_id == company_id,
                Project.status.in_(("planning", "active", "review")),
            ).limit(1)
        )
        project = result.scalar_one_or_none()
        if not project:
            return "No project available for task"
        project_id = project.id
    else:
        project_id = UUID(str(project_id))

    title = config.get("title") or "Follow-up task"
    task = Task(
        company_id=company_id,
        project_id=project_id,
        title=title,
        description=config.get("description") or "Created by automation",
        status="todo",
        priority=config.get("priority") or "medium",
    )
    db.add(task)
    await db.flush()
    return f"Task created: {title}"


async def _update_status_action(db: AsyncSession, company_id: UUID, ctx: dict, config: dict) -> str:
    new_status = config.get("status")
    if not new_status:
        return "No status configured"
    entity_type = ctx.get("entity_type")
    entity_id = ctx.get("entity_id")
    if not entity_id:
        return "No entity"
    if entity_type == "lead":
        lead = await db.get(Lead, UUID(str(entity_id)))
        if lead and lead.company_id == company_id:
            lead.status = new_status
            await db.flush()
            return f"Lead status → {new_status}"
    if entity_type == "task":
        task = await db.get(Task, UUID(str(entity_id)))
        if task and task.company_id == company_id:
            task.status = new_status
            await db.flush()
            return f"Task status → {new_status}"
    if entity_type == "project":
        project = await db.get(Project, UUID(str(entity_id)))
        if project and project.company_id == company_id:
            project.status = new_status
            await db.flush()
            return f"Project status → {new_status}"
    return "Status not updated"


async def _notify_role(
    db: AsyncSession,
    company_id: UUID,
    role_name: str,
    ctx: dict,
    config: dict,
) -> str:
    result = await db.execute(
        select(User)
        .options(selectinload(User.role))
        .where(User.company_id == company_id, User.is_active.is_(True))
    )
    recipients = [u for u in result.scalars().all() if u.role and u.role.name == role_name]
    if not recipients:
        return f"No {role_name} found"
    subject = config.get("subject") or f"AgencyFlow alert: {ctx.get('trigger_key', 'event')}"
    body = config.get("body") or f"Automation notification for {ctx.get('entity_type')} {ctx.get('entity_id')}"
    sent_count = 0
    for user in recipients:
        ok, _ = await send_custom_email(user.email, subject, body)
        if ok:
            sent_count += 1
    return f"Notified {len(recipients)} {role_name}(s) ({sent_count} emailed)"


async def _call_webhook(config: dict, ctx: dict) -> str:
    url = config.get("url")
    if not url:
        return "No webhook URL"
    payload = {"context": ctx, "config": config}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
        return f"Webhook {resp.status_code}"
    except Exception as exc:  # noqa: BLE001
        return f"Webhook failed: {exc}"
