from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.automation_engine import fire_trigger
from app.core.deps import CurrentUser, require_permission, require_staff
from app.core.realtime import realtime_manager
from app.core.record_360 import build_record_360
from app.db.session import get_db
from app.models.client import Client
from app.models.project import Project
from app.models.project_expense import ProjectExpense
from app.models.task import Task
from app.models.user import User
from app.schemas.common import MessageResponse
from app.schemas.expense import (
    EXPENSE_CATEGORIES,
    VALID_EXPENSE_CATEGORIES,
    ExpenseCategoryBreakdown,
    ExpenseCreate,
    ExpenseOut,
    ExpenseUpdate,
    ProjectProfitability,
)
from app.schemas.project import ProjectCreate, ProjectOut, ProjectUpdate
from app.schemas.record_360 import Record360View

router = APIRouter(prefix="/projects", tags=["projects"])

PROJECT_STATUSES = {"planning", "active", "review", "completed"}


@router.get("", response_model=list[ProjectOut])
async def list_projects(
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    q = (
        select(Project)
        .options(selectinload(Project.tasks))
        .where(Project.company_id == current.company_id)
        .order_by(Project.created_at.desc())
    )
    if current.role_name == "employee" and not current.can("manage_projects"):
        assigned_ids = await _assigned_project_ids(db, current.company_id, current.id)
        if not assigned_ids:
            return []
        q = q.where(Project.id.in_(assigned_ids))
    result = await db.execute(q)
    projects = result.scalars().all()
    return [_project_out(p) for p in projects]


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: ProjectCreate,
    current: CurrentUser = Depends(require_permission("manage_projects")),
    db: AsyncSession = Depends(get_db),
):
    if body.status not in PROJECT_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid project status")
    client = await db.execute(
        select(Client).where(Client.id == body.client_id, Client.company_id == current.company_id)
    )
    if not client.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Client not found in workspace")

    project = Project(
        company_id=current.company_id,
        created_by=current.id,
        **body.model_dump(),
    )
    db.add(project)
    await db.flush()
    await db.refresh(project, ["tasks"])
    await realtime_manager.broadcast(current.company_id, "project", f"Project created: {project.title}")
    return _project_out(project)


@router.get("/expense-categories")
async def list_expense_categories(current: CurrentUser = Depends(require_staff)):
    return EXPENSE_CATEGORIES


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(
    project_id: UUID,
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    project = await _get_project(db, project_id, current.company_id)
    await _ensure_project_access(db, project, current)
    return _project_out(project)


@router.get("/{project_id}/360", response_model=Record360View)
async def get_project_360(
    project_id: UUID,
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    project = await _get_project(db, project_id, current.company_id)
    await _ensure_project_access(db, project, current)
    return await build_record_360(db, current.company_id, current.id, "project", project_id)


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(
    project_id: UUID,
    body: ProjectUpdate,
    current: CurrentUser = Depends(require_permission("manage_projects")),
    db: AsyncSession = Depends(get_db),
):
    project = await _get_project(db, project_id, current.company_id)
    data = body.model_dump(exclude_unset=True)
    if "status" in data and data["status"] not in PROJECT_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid project status")
    if "client_id" in data:
        client = await db.execute(
            select(Client).where(Client.id == data["client_id"], Client.company_id == current.company_id)
        )
        if not client.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Client not found")
    old_status = project.status
    for k, v in data.items():
        setattr(project, k, v)
    await db.flush()
    await db.refresh(project, ["tasks"])
    if data.get("status") == "completed" and old_status != "completed":
        await fire_trigger(
            db,
            company_id=current.company_id,
            trigger_key="project_completed",
            entity_type="project",
            entity_id=project.id,
            context={"project_id": str(project.id), "name": project.title},
        )
    await realtime_manager.broadcast(current.company_id, "project", f"Project updated: {project.title}")
    return _project_out(project)


@router.delete("/{project_id}", response_model=MessageResponse)
async def delete_project(
    project_id: UUID,
    current: CurrentUser = Depends(require_permission("manage_projects")),
    db: AsyncSession = Depends(get_db),
):
    project = await _get_project(db, project_id, current.company_id)
    title = project.title
    await db.delete(project)
    await realtime_manager.broadcast(current.company_id, "project", f"Project removed: {title}")
    return MessageResponse(message="Project deleted")


@router.get("/{project_id}/expenses", response_model=list[ExpenseOut])
async def list_project_expenses(
    project_id: UUID,
    current: CurrentUser = Depends(require_permission("manage_projects")),
    db: AsyncSession = Depends(get_db),
):
    await _get_project(db, project_id, current.company_id)
    result = await db.execute(
        select(ProjectExpense)
        .where(
            ProjectExpense.project_id == project_id,
            ProjectExpense.company_id == current.company_id,
        )
        .order_by(ProjectExpense.expense_date.desc())
    )
    expenses = list(result.scalars().all())
    return [await _expense_out(db, e) for e in expenses]


@router.post("/{project_id}/expenses", response_model=ExpenseOut, status_code=status.HTTP_201_CREATED)
async def create_project_expense(
    project_id: UUID,
    body: ExpenseCreate,
    current: CurrentUser = Depends(require_permission("manage_projects")),
    db: AsyncSession = Depends(get_db),
):
    await _get_project(db, project_id, current.company_id)
    if body.category not in VALID_EXPENSE_CATEGORIES:
        raise HTTPException(status_code=400, detail="Invalid expense category")
    expense = ProjectExpense(
        company_id=current.company_id,
        project_id=project_id,
        created_by_id=current.id,
        category=body.category,
        title=body.title,
        amount=body.amount,
        expense_date=body.expense_date,
        notes=body.notes,
    )
    db.add(expense)
    await db.flush()
    await realtime_manager.broadcast(
        current.company_id, "expense", f"Expense added: {expense.title}"
    )
    return await _expense_out(db, expense)


@router.patch("/{project_id}/expenses/{expense_id}", response_model=ExpenseOut)
async def update_project_expense(
    project_id: UUID,
    expense_id: UUID,
    body: ExpenseUpdate,
    current: CurrentUser = Depends(require_permission("manage_projects")),
    db: AsyncSession = Depends(get_db),
):
    expense = await _get_expense(db, project_id, expense_id, current.company_id)
    data = body.model_dump(exclude_unset=True)
    if "category" in data and data["category"] not in VALID_EXPENSE_CATEGORIES:
        raise HTTPException(status_code=400, detail="Invalid expense category")
    for k, v in data.items():
        setattr(expense, k, v)
    await db.flush()
    return await _expense_out(db, expense)


@router.delete("/{project_id}/expenses/{expense_id}", response_model=MessageResponse)
async def delete_project_expense(
    project_id: UUID,
    expense_id: UUID,
    current: CurrentUser = Depends(require_permission("manage_projects")),
    db: AsyncSession = Depends(get_db),
):
    expense = await _get_expense(db, project_id, expense_id, current.company_id)
    await db.delete(expense)
    return MessageResponse(message="Expense deleted")


@router.get("/{project_id}/profitability", response_model=ProjectProfitability)
async def project_profitability(
    project_id: UUID,
    current: CurrentUser = Depends(require_permission("manage_projects")),
    db: AsyncSession = Depends(get_db),
):
    project = await _get_project(db, project_id, current.company_id)
    result = await db.execute(
        select(ProjectExpense.category, func.sum(ProjectExpense.amount))
        .where(
            ProjectExpense.project_id == project_id,
            ProjectExpense.company_id == current.company_id,
        )
        .group_by(ProjectExpense.category)
    )
    label_map = {c["key"]: c["label"] for c in EXPENSE_CATEGORIES}
    breakdown: list[ExpenseCategoryBreakdown] = []
    expenses_total = 0.0
    for category, amount in result.all():
        amt = float(amount or 0)
        expenses_total += amt
        breakdown.append(
            ExpenseCategoryBreakdown(
                category=category,
                label=label_map.get(category, category.title()),
                amount=amt,
            )
        )
    breakdown.sort(key=lambda x: -x.amount)
    revenue = float(project.budget or 0)
    profit = revenue - expenses_total
    return ProjectProfitability(
        project_id=project.id,
        project_title=project.title,
        revenue=revenue,
        expenses_total=expenses_total,
        profit=profit,
        breakdown=breakdown,
    )


def _category_label(key: str) -> str:
    for c in EXPENSE_CATEGORIES:
        if c["key"] == key:
            return c["label"]
    return key.replace("_", " ").title()


async def _creator_name(db: AsyncSession, user_id: UUID | None) -> str | None:
    if not user_id:
        return None
    user = await db.get(User, user_id)
    if not user:
        return None
    return f"{user.first_name} {user.last_name or ''}".strip()


async def _expense_out(db: AsyncSession, expense: ProjectExpense) -> ExpenseOut:
    return ExpenseOut(
        id=expense.id,
        company_id=expense.company_id,
        project_id=expense.project_id,
        created_by_id=expense.created_by_id,
        created_by_name=await _creator_name(db, expense.created_by_id),
        category=expense.category,
        category_label=_category_label(expense.category),
        title=expense.title,
        amount=float(expense.amount or 0),
        expense_date=expense.expense_date,
        notes=expense.notes,
        created_at=expense.created_at,
    )


async def _get_expense(
    db: AsyncSession, project_id: UUID, expense_id: UUID, company_id: UUID
) -> ProjectExpense:
    result = await db.execute(
        select(ProjectExpense).where(
            ProjectExpense.id == expense_id,
            ProjectExpense.project_id == project_id,
            ProjectExpense.company_id == company_id,
        )
    )
    expense = result.scalar_one_or_none()
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found")
    return expense


def _project_out(project: Project) -> ProjectOut:
    tasks = project.tasks or []
    total = len(tasks)
    done = sum(1 for t in tasks if t.status == "done")
    progress = int((done / total) * 100) if total else 0
    return ProjectOut(
        id=project.id,
        company_id=project.company_id,
        client_id=project.client_id,
        title=project.title,
        description=project.description,
        status=project.status,
        budget=project.budget,
        estimated_hours=project.estimated_hours or 0,
        start_date=project.start_date,
        end_date=project.end_date,
        created_by=project.created_by,
        created_at=project.created_at,
        task_total=total,
        task_done=done,
        progress_percent=progress,
    )


async def _get_project(db: AsyncSession, project_id: UUID, company_id: UUID) -> Project:
    result = await db.execute(
        select(Project)
        .options(selectinload(Project.tasks))
        .where(Project.id == project_id, Project.company_id == company_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


async def _assigned_project_ids(db: AsyncSession, company_id: UUID, user_id: UUID) -> set[UUID]:
    result = await db.execute(
        select(Task.project_id)
        .where(Task.company_id == company_id, Task.assigned_to == user_id)
        .distinct()
    )
    return set(result.scalars().all())


async def _ensure_project_access(db: AsyncSession, project: Project, current: CurrentUser) -> None:
    if current.role_name != "employee" or current.can("manage_projects"):
        return
    assigned_ids = await _assigned_project_ids(db, current.company_id, current.id)
    if project.id not in assigned_ids:
        raise HTTPException(status_code=403, detail="You can only view assigned projects")
