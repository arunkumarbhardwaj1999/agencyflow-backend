from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from app.core.automation_engine import fire_trigger
from app.core.deps import CurrentUser, require_company, require_permission
from app.core.realtime import realtime_manager
from app.core.whatsapp import render_template
from app.db.session import get_db
from app.models.client import Client
from app.models.project import Project
from app.models.task import Task
from app.schemas.common import MessageResponse
from app.schemas.task import TaskCreate, TaskOut, TaskUpdate
from app.services.whatsapp_service import enqueue_whatsapp

router = APIRouter(prefix="/tasks", tags=["tasks"])
logger = logging.getLogger("agencyflow.tasks")

TASK_STATUSES = {"todo", "in_progress", "review", "done"}
TASK_PRIORITIES = {"low", "medium", "high", "urgent"}


@router.get("", response_model=list[TaskOut])
async def list_tasks(
    project_id: UUID | None = None,
    current: CurrentUser = Depends(require_company),
    db: AsyncSession = Depends(get_db),
):
    if current.role_name == "client":
        raise HTTPException(status_code=403, detail="Use the client portal for your tasks")
    q = select(Task).where(Task.company_id == current.company_id).order_by(Task.created_at.desc())
    if project_id:
        q = q.where(Task.project_id == project_id)
    if current.role_name == "employee" and not current.can("manage_tasks"):
        q = q.where(Task.assigned_to == current.id)
    result = await db.execute(q)
    return list(result.scalars().all())


@router.post("", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
async def create_task(
    body: TaskCreate,
    current: CurrentUser = Depends(require_permission("manage_tasks")),
    db: AsyncSession = Depends(get_db),
):
    await _validate_task_fields(body.status, body.priority)
    await _ensure_project(db, body.project_id, current.company_id)
    task = Task(company_id=current.company_id, **body.model_dump())
    db.add(task)
    await db.flush()
    await db.refresh(task)
    await realtime_manager.broadcast(current.company_id, "task", f"Task created: {task.title}")
    return task


@router.get("/{task_id}", response_model=TaskOut)
async def get_task(
    task_id: UUID,
    current: CurrentUser = Depends(require_company),
    db: AsyncSession = Depends(get_db),
):
    return await _get_task(db, task_id, current)


@router.patch("/{task_id}", response_model=TaskOut)
async def update_task(
    task_id: UUID,
    body: TaskUpdate,
    current: CurrentUser = Depends(require_company),
    db: AsyncSession = Depends(get_db),
):
    task = await _get_task(db, task_id, current)
    if not current.can("manage_tasks"):
        if task.assigned_to != current.id:
            raise HTTPException(status_code=403, detail="Can only update assigned tasks")
        allowed = {"status", "description"}
        data = {k: v for k, v in body.model_dump(exclude_unset=True).items() if k in allowed}
    else:
        data = body.model_dump(exclude_unset=True)

    if not data:
        return task

    if "status" in data:
        await _validate_task_fields(data["status"], data.get("priority", task.priority))
    if "priority" in data:
        await _validate_task_fields(task.status, data["priority"])

    old_status = task.status
    for k, v in data.items():
        setattr(task, k, v)
    # Persist status first so notify/automation failures cannot roll it back
    # and so realtime refetch cannot read a stale value.
    await db.commit()
    await db.refresh(task)

    try:
        await realtime_manager.broadcast(
            current.company_id, "task", f"Task updated: {task.title} ({task.status})"
        )
    except Exception:
        logger.exception("Realtime broadcast failed for task %s", task.id)

    if "status" in data and data["status"] == "done" and old_status != "done":
        try:
            await _maybe_notify_task_done(db, task, current.company_id)
            await fire_trigger(
                db,
                company_id=current.company_id,
                trigger_key="task_completed",
                entity_type="task",
                entity_id=task.id,
                context={"project_id": str(task.project_id), "name": task.title},
            )
            await db.commit()
        except Exception:
            logger.exception("Post-complete side effects failed for task %s", task.id)
            await db.rollback()
            # Re-load after rollback so response serialization does not hit an expired instance
            result = await db.execute(select(Task).where(Task.id == task_id))
            task = result.scalar_one()

    return task


@router.delete("/{task_id}", response_model=MessageResponse)
async def delete_task(
    task_id: UUID,
    current: CurrentUser = Depends(require_permission("manage_tasks")),
    db: AsyncSession = Depends(get_db),
):
    task = await _get_task(db, task_id, current)
    task_title = task.title
    await db.delete(task)
    await realtime_manager.broadcast(current.company_id, "task", f"Task removed: {task_title}")
    return MessageResponse(message="Task deleted")


async def _validate_task_fields(status: str, priority: str) -> None:
    if status not in TASK_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid task status")
    if priority not in TASK_PRIORITIES:
        raise HTTPException(status_code=400, detail="Invalid priority")


async def _ensure_project(db: AsyncSession, project_id: UUID, company_id: UUID) -> None:
    result = await db.execute(select(Project).where(Project.id == project_id, Project.company_id == company_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Project not found")


async def _get_task(db: AsyncSession, task_id: UUID, current: CurrentUser) -> Task:
    if current.role_name == "client":
        raise HTTPException(status_code=403, detail="Use the client portal for your tasks")
    result = await db.execute(
        select(Task).where(Task.id == task_id, Task.company_id == current.company_id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if current.role_name == "employee" and not current.can("manage_tasks"):
        if task.assigned_to != current.id:
            raise HTTPException(status_code=403, detail="You can only view assigned tasks")
    return task


async def _maybe_notify_task_done(db: AsyncSession, task: Task, company_id: UUID) -> None:
    try:
        project = await db.get(Project, task.project_id)
        if not project:
            return
        client = await db.get(Client, project.client_id)
        if not client or not client.phone:
            return
        params = {
            "name": client.business_name or client.name or "Client",
            "project_title": project.title or "Project",
            "detail": f'Task "{task.title}" is complete.',
        }
        message = render_template("task_update", **params)
        enqueue_whatsapp(
            company_id=company_id,
            client_id=client.id,
            phone=client.phone,
            message=message,
            template_key="task_update",
            params=params,
        )
    except Exception:
        logger.exception("WhatsApp task-done notify failed for task %s", task.id)
