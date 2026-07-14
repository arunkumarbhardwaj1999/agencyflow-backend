from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.core.config import get_settings
from app.core.deps import CurrentUser, require_permission, require_staff
from app.db.session import get_db
from app.models.company import Company
from app.models.document import Document
from app.models.project import Project
from app.models.task import Task
from app.schemas.common import MessageResponse
from app.schemas.document import DocumentOut, LogoOut

router = APIRouter(prefix="/files", tags=["files"])
settings = get_settings()

LOGO_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/webp", "image/svg+xml"}


def _max_bytes() -> int:
    return settings.max_upload_mb * 1024 * 1024


async def _read_upload(file: UploadFile) -> bytes:
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(data) > _max_bytes():
        raise HTTPException(
            status_code=413, detail=f"File too large (max {settings.max_upload_mb} MB)"
        )
    return data


def _doc_out(doc: Document) -> DocumentOut:
    return DocumentOut(
        id=doc.id,
        project_id=doc.project_id,
        invoice_id=doc.invoice_id,
        lead_id=doc.lead_id,
        deal_id=doc.deal_id,
        filename=doc.filename,
        content_type=doc.content_type,
        size=doc.size,
        kind=doc.kind,
        created_at=doc.created_at,
    )


@router.get("/logo", response_model=LogoOut)
async def get_logo(
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    company = await db.get(Company, current.company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return LogoOut(logo=company.logo)


@router.post("/logo", response_model=LogoOut)
async def upload_logo(
    file: UploadFile = File(...),
    current: CurrentUser = Depends(require_permission("manage_staff")),
    db: AsyncSession = Depends(get_db),
):
    if file.content_type not in LOGO_TYPES:
        raise HTTPException(status_code=400, detail="Logo must be PNG, JPG, WEBP or SVG")
    data = await _read_upload(file)

    company = await db.get(Company, current.company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Workspace not found")

    key = storage.build_key(current.company_id, "logo", file.filename or "logo")
    await storage.save(key, data, file.content_type or "image/png")
    company.logo = storage.public_url(key)
    await db.flush()
    return LogoOut(logo=company.logo)


@router.post("/documents", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    project_id: UUID | None = Form(None),
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    if not current.company_id:
        raise HTTPException(status_code=400, detail="No workspace associated")

    if project_id is not None:
        result = await db.execute(
            select(Project).where(
                Project.id == project_id, Project.company_id == current.company_id
            )
        )
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Project not found")
        if current.role_name == "employee" and not current.can("manage_projects"):
            await _ensure_employee_project(db, current, project_id)

    data = await _read_upload(file)
    content_type = file.content_type or storage.guess_content_type(file.filename or "")
    key = storage.build_key(current.company_id, "documents", file.filename or "file")
    await storage.save(key, data, content_type)

    doc = Document(
        company_id=current.company_id,
        project_id=project_id,
        uploaded_by=current.id,
        filename=file.filename or "file",
        content_type=content_type,
        size=len(data),
        storage_key=key,
        kind="document",
    )
    db.add(doc)
    await db.flush()
    return _doc_out(doc)


@router.get("/documents", response_model=list[DocumentOut])
async def list_documents(
    project_id: UUID | None = None,
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    q = (
        select(Document)
        .where(Document.company_id == current.company_id, Document.kind == "document")
        .order_by(Document.created_at.desc())
    )
    if project_id is not None:
        if current.role_name == "employee" and not current.can("manage_projects"):
            await _ensure_employee_project(db, current, project_id)
        q = q.where(Document.project_id == project_id)
    elif current.role_name == "employee" and not current.can("manage_projects"):
        assigned = await _assigned_project_ids(db, current.company_id, current.id)
        if assigned:
            q = q.where(or_(Document.project_id.in_(assigned), Document.uploaded_by == current.id))
        else:
            q = q.where(Document.uploaded_by == current.id)
    result = await db.execute(q)
    return [_doc_out(d) for d in result.scalars().all()]


async def _get_document(db: AsyncSession, doc_id: UUID, company_id) -> Document:
    result = await db.execute(
        select(Document).where(Document.id == doc_id, Document.company_id == company_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


async def _assigned_project_ids(db: AsyncSession, company_id: UUID, user_id: UUID) -> set[UUID]:
    result = await db.execute(
        select(Task.project_id)
        .where(Task.company_id == company_id, Task.assigned_to == user_id)
        .distinct()
    )
    return set(result.scalars().all())


async def _ensure_employee_project(db: AsyncSession, current: CurrentUser, project_id: UUID) -> None:
    assigned = await _assigned_project_ids(db, current.company_id, current.id)
    if project_id not in assigned:
        raise HTTPException(status_code=403, detail="You can only access documents for assigned projects")


async def _ensure_document_access(db: AsyncSession, current: CurrentUser, doc: Document) -> None:
    if current.role_name != "employee" or current.can("manage_projects"):
        return
    if doc.uploaded_by == current.id:
        return
    if doc.project_id and doc.project_id in await _assigned_project_ids(db, current.company_id, current.id):
        return
    raise HTTPException(status_code=403, detail="You do not have access to this document")


@router.get("/documents/{doc_id}/download")
async def download_document(
    doc_id: UUID,
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    doc = await _get_document(db, doc_id, current.company_id)
    await _ensure_document_access(db, current, doc)
    try:
        data = await storage.load(doc.storage_key)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File no longer available") from None
    return Response(
        content=data,
        media_type=doc.content_type,
        headers={"Content-Disposition": f'attachment; filename="{doc.filename}"'},
    )


@router.delete("/documents/{doc_id}", response_model=MessageResponse)
async def delete_document(
    doc_id: UUID,
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    doc = await _get_document(db, doc_id, current.company_id)
    await _ensure_document_access(db, current, doc)
    await storage.delete(doc.storage_key)
    await db.delete(doc)
    return MessageResponse(message="Document deleted")


@router.get("/public/{key:path}")
async def serve_public(key: str):
    """Serve locally-stored files (dev mock mode only). In production R2 serves
    objects directly via its public/CDN URL, so this route is never used."""
    if settings.storage_enabled:
        raise HTTPException(status_code=404, detail="Not found")
    try:
        data = await storage.load(key)
    except (FileNotFoundError, ValueError):
        raise HTTPException(status_code=404, detail="Not found") from None
    return Response(content=data, media_type=storage.guess_content_type(key))
