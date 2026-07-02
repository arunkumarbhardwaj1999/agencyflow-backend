import json
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.ai import (
    AIError,
    draft_client_welcome,
    draft_invoice_email,
    draft_lead_email,
    polish_task_description,
    stream_complete,
    suggest_followups,
    summarize_project,
)
from app.core.config import get_settings
from app.core.deps import CurrentUser, require_staff
from app.core.limiter import limiter, user_or_ip_key
from app.db.session import get_db
from app.models.client import Client
from app.models.company import Company
from app.models.invoice import Invoice
from app.models.lead import Lead
from app.models.project import Project
from app.models.task import Task
from app.schemas.ai import (
    AIResponse,
    AIStreamRequest,
    ClientAIRequest,
    InvoiceAIRequest,
    LeadAIRequest,
    ProjectAIRequest,
    TaskAIRequest,
)

router = APIRouter(prefix="/ai", tags=["ai"])
settings = get_settings()


def _mode() -> str:
    return "live" if settings.ai_enabled else "mock"


async def _build_prompt(action: str, body: AIStreamRequest, db: AsyncSession, current: CurrentUser) -> tuple[str, str]:
    company = await db.get(Company, current.company_id)
    agency = company.company_name if company else "AgencyFlow"

    if action == "draft-email":
        if not body.lead_id:
            raise HTTPException(status_code=400, detail="lead_id required")
        result = await db.execute(
            select(Lead).where(Lead.id == body.lead_id, Lead.company_id == current.company_id)
        )
        lead = result.scalar_one_or_none()
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")
        system = (
            "You are a professional copywriter for an Indian digital agency. "
            "Write concise, warm client emails. Use INR when mentioning money."
        )
        prompt = (
            f"Draft a short follow-up email to a sales lead.\n\n"
            f"Agency: {agency}\nLead name: {lead.name}\n"
            f"Company: {lead.company_name or 'N/A'}\nPipeline stage: {lead.status}\n"
            f"Deal value: ₹{lead.value}\nNotes: {lead.notes or 'None'}\n\n"
            f"Include a subject line. Keep it under 150 words."
        )
        return system, prompt

    if action == "summarize-project":
        if not body.project_id:
            raise HTTPException(status_code=400, detail="project_id required")
        result = await db.execute(
            select(Project)
            .options(selectinload(Project.tasks))
            .where(Project.id == body.project_id, Project.company_id == current.company_id)
        )
        project = result.scalar_one_or_none()
        if not project:
            raise HTTPException(status_code=404, detail="Project not found")
        client = await db.get(Client, project.client_id)
        tasks: list[Task] = project.tasks
        done = sum(1 for t in tasks if t.status == "done")
        system = "You summarize agency project status for internal standups. Use bullet points."
        prompt = (
            f"Summarize this project for the team:\n\n"
            f"Project: {project.title}\nClient: {client.business_name if client else 'Client'}\n"
            f"Status: {project.status}\nBudget: ₹{project.budget}\n"
            f"Tasks: {done}/{len(tasks)} done\nDescription: {project.description or 'N/A'}\n\n"
            f"Highlight progress, blockers, and suggested next actions."
        )
        return system, prompt

    if action == "suggest-followups":
        result = await db.execute(
            select(Lead)
            .where(Lead.company_id == current.company_id, Lead.status.notin_(["won", "lost"]))
            .order_by(Lead.next_followup.asc().nulls_last())
            .limit(20)
        )
        leads = result.scalars().all()
        summary = []
        now = datetime.now(UTC)
        for lead in leads:
            followup = "none"
            if lead.next_followup:
                fu = lead.next_followup
                if fu.tzinfo is None:
                    fu = fu.replace(tzinfo=UTC)
                followup = "overdue" if fu < now else fu.date().isoformat()
            summary.append(
                {"name": lead.name, "status": lead.status, "value": str(lead.value), "followup": followup}
            )
        lines = "\n".join(
            f"- {l['name']} ({l['status']}), value ₹{l['value']}, follow-up: {l['followup']}"
            for l in summary[:15]
        )
        system = "You are a sales coach for a digital agency CRM. Be specific and actionable."
        prompt = (
            f"Agency: {agency}\n\nOpen leads:\n{lines or 'No open leads.'}\n\n"
            f"Suggest 3–5 follow-up actions for today, prioritizing overdue follow-ups."
        )
        return system, prompt

    if action == "draft-invoice-email":
        if not body.invoice_id:
            raise HTTPException(status_code=400, detail="invoice_id required")
        result = await db.execute(
            select(Invoice).where(Invoice.id == body.invoice_id, Invoice.company_id == current.company_id)
        )
        invoice = result.scalar_one_or_none()
        if not invoice:
            raise HTTPException(status_code=404, detail="Invoice not found")
        client = await db.get(Client, invoice.client_id)
        system = (
            "You write professional invoice emails for an Indian digital agency. "
            "Be clear about amount, due date, and payment. Use ₹ for INR."
        )
        prompt = (
            f"Draft an email to send an invoice to a client.\n\n"
            f"Agency: {agency}\nClient: {client.business_name if client else 'Client'}\n"
            f"Invoice: {invoice.invoice_number}\nAmount: ₹{invoice.total}\n"
            f"Due date: {invoice.due_date}\n\n"
            f"Include subject line. Mention PDF attachment and online payment. Under 120 words."
        )
        return system, prompt

    if action == "polish-task":
        if not body.task_id:
            raise HTTPException(status_code=400, detail="task_id required")
        result = await db.execute(
            select(Task).where(Task.id == body.task_id, Task.company_id == current.company_id)
        )
        task = result.scalar_one_or_none()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        project = await db.get(Project, task.project_id)
        system = "You improve task descriptions for agency project management. Be specific and actionable."
        prompt = (
            f"Polish this task description for clarity:\n\n"
            f"Project: {project.title if project else 'Project'}\nTask: {task.title}\n"
            f"Current description: {task.description or 'None'}\n\n"
            f"Return only the improved description (2–4 sentences)."
        )
        return system, prompt

    if action == "draft-client-welcome":
        if not body.client_id:
            raise HTTPException(status_code=400, detail="client_id required")
        client = await db.get(Client, body.client_id)
        if not client or client.company_id != current.company_id:
            raise HTTPException(status_code=404, detail="Client not found")
        project_title = None
        if body.project_id:
            project = await db.get(Project, body.project_id)
            if project and project.company_id == current.company_id:
                project_title = project.title
        system = (
            "You write warm onboarding emails for new agency clients in India. "
            "Mention the client portal and next steps."
        )
        prompt = (
            f"Draft a welcome email for a new client.\n\n"
            f"Agency: {agency}\nClient: {client.business_name}\n"
            f"First project: {project_title or 'To be confirmed'}\n\n"
            f"Include subject line. Under 130 words."
        )
        return system, prompt

    raise HTTPException(status_code=400, detail=f"Unknown action: {action}")


@router.post("/draft-email", response_model=AIResponse)
@limiter.limit(settings.ai_rate_limit, key_func=user_or_ip_key)
async def ai_draft_email(
    request: Request,
    body: LeadAIRequest,
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Lead).where(Lead.id == body.lead_id, Lead.company_id == current.company_id)
    )
    lead = result.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    company = await db.get(Company, current.company_id)
    try:
        content = await draft_lead_email(
            lead_name=lead.name,
            company_name=lead.company_name,
            status=lead.status,
            value=str(lead.value),
            notes=lead.notes,
            agency_name=company.company_name if company else "AgencyFlow",
        )
    except AIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return AIResponse(content=content, mode=_mode())


@router.post("/draft-invoice-email", response_model=AIResponse)
@limiter.limit(settings.ai_rate_limit, key_func=user_or_ip_key)
async def ai_draft_invoice_email(
    request: Request,
    body: InvoiceAIRequest,
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Invoice).where(Invoice.id == body.invoice_id, Invoice.company_id == current.company_id)
    )
    invoice = result.scalar_one_or_none()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    client = await db.get(Client, invoice.client_id)
    company = await db.get(Company, current.company_id)
    try:
        content = await draft_invoice_email(
            client_name=client.business_name if client else "Client",
            invoice_number=invoice.invoice_number,
            amount=str(invoice.total),
            due_date=str(invoice.due_date),
            agency_name=company.company_name if company else "AgencyFlow",
        )
    except AIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return AIResponse(content=content, mode=_mode())


@router.post("/polish-task", response_model=AIResponse)
@limiter.limit(settings.ai_rate_limit, key_func=user_or_ip_key)
async def ai_polish_task(
    request: Request,
    body: TaskAIRequest,
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Task).where(Task.id == body.task_id, Task.company_id == current.company_id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    project = await db.get(Project, task.project_id)
    try:
        content = await polish_task_description(
            title=task.title,
            description=task.description,
            project_title=project.title if project else "Project",
        )
    except AIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return AIResponse(content=content, mode=_mode())


@router.post("/draft-client-welcome", response_model=AIResponse)
@limiter.limit(settings.ai_rate_limit, key_func=user_or_ip_key)
async def ai_draft_client_welcome(
    request: Request,
    body: ClientAIRequest,
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    client = await db.get(Client, body.client_id)
    if not client or client.company_id != current.company_id:
        raise HTTPException(status_code=404, detail="Client not found")
    company = await db.get(Company, current.company_id)
    project_title = None
    if body.project_id:
        project = await db.get(Project, body.project_id)
        if project and project.company_id == current.company_id:
            project_title = project.title
    try:
        content = await draft_client_welcome(
            client_name=client.business_name,
            agency_name=company.company_name if company else "AgencyFlow",
            project_title=project_title,
        )
    except AIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return AIResponse(content=content, mode=_mode())


@router.post("/summarize-project", response_model=AIResponse)
@limiter.limit(settings.ai_rate_limit, key_func=user_or_ip_key)
async def ai_summarize_project(
    request: Request,
    body: ProjectAIRequest,
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Project)
        .options(selectinload(Project.tasks))
        .where(Project.id == body.project_id, Project.company_id == current.company_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    client = await db.get(Client, project.client_id)
    tasks: list[Task] = project.tasks
    done = sum(1 for t in tasks if t.status == "done")
    try:
        content = await summarize_project(
            title=project.title,
            status=project.status,
            budget=str(project.budget),
            task_total=len(tasks),
            task_done=done,
            client_name=client.business_name if client else "Client",
            description=project.description,
        )
    except AIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return AIResponse(content=content, mode=_mode())


@router.post("/suggest-followups", response_model=AIResponse)
@limiter.limit(settings.ai_rate_limit, key_func=user_or_ip_key)
async def ai_suggest_followups(
    request: Request,
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Lead)
        .where(Lead.company_id == current.company_id, Lead.status.notin_(["won", "lost"]))
        .order_by(Lead.next_followup.asc().nulls_last())
        .limit(20)
    )
    leads = result.scalars().all()
    company = await db.get(Company, current.company_id)

    summary = []
    now = datetime.now(UTC)
    for lead in leads:
        followup = "none"
        if lead.next_followup:
            fu = lead.next_followup
            if fu.tzinfo is None:
                fu = fu.replace(tzinfo=UTC)
            followup = "overdue" if fu < now else fu.date().isoformat()
        summary.append(
            {"name": lead.name, "status": lead.status, "value": str(lead.value), "followup": followup}
        )

    try:
        content = await suggest_followups(
            leads_summary=summary,
            agency_name=company.company_name if company else "AgencyFlow",
        )
    except AIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return AIResponse(content=content, mode=_mode())


@router.post("/stream")
@limiter.limit(settings.ai_rate_limit, key_func=user_or_ip_key)
async def ai_stream(
    request: Request,
    body: AIStreamRequest,
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    mode = _mode()

    async def event_generator():
        try:
            system, prompt = await _build_prompt(body.action, body, db, current)
            async for chunk in stream_complete(system, prompt):
                payload = json.dumps({"chunk": chunk, "done": False, "mode": mode})
                yield f"data: {payload}\n\n"
            yield f"data: {json.dumps({'chunk': '', 'done': True, 'mode': mode})}\n\n"
        except HTTPException as exc:
            payload = json.dumps({"error": exc.detail, "done": True, "mode": mode})
            yield f"data: {payload}\n\n"
        except AIError as exc:
            payload = json.dumps({"error": str(exc), "done": True, "mode": mode})
            yield f"data: {payload}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
