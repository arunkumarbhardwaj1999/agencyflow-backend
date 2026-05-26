from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.deps import CurrentUser, require_company, require_permission
from app.db.session import get_db
from app.models.client import Client
from app.models.project import Project
from app.models.task import Task
from app.schemas.common import MessageResponse
from app.schemas.project import ProjectCreate, ProjectOut, ProjectUpdate

router = APIRouter(prefix="/projects", tags=["projects"])

PROJECT_STATUSES = {"planning", "active", "review", "completed"}


@router.get("", response_model=list[ProjectOut])
async def list_projects(
    current: CurrentUser = Depends(require_company),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Project)
        .options(selectinload(Project.tasks))
        .where(Project.company_id == current.company_id)
        .order_by(Project.created_at.desc())
    )
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
    return _project_out(project)


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(
    project_id: UUID,
    current: CurrentUser = Depends(require_company),
    db: AsyncSession = Depends(get_db),
):
    project = await _get_project(db, project_id, current.company_id)
    return _project_out(project)


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
    for k, v in data.items():
        setattr(project, k, v)
    await db.flush()
    await db.refresh(project, ["tasks"])
    return _project_out(project)


@router.delete("/{project_id}", response_model=MessageResponse)
async def delete_project(
    project_id: UUID,
    current: CurrentUser = Depends(require_permission("manage_projects")),
    db: AsyncSession = Depends(get_db),
):
    project = await _get_project(db, project_id, current.company_id)
    await db.delete(project)
    return MessageResponse(message="Project deleted")


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
