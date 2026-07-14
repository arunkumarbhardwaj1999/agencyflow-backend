from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.core.config import get_settings
from app.core.deps import CurrentUser, require_permission, require_staff
from app.core.document_folders import (
    CLIENT_DOCUMENT_FOLDERS,
    VALID_FOLDER_KEYS,
    folder_label,
    suggest_document_folder,
)
from app.core.email import send_custom_email, split_subject_body
from app.core.plans import assert_can_add_client
from app.core.realtime import realtime_manager
from app.core.record_360 import build_record_360
from app.db.session import get_db
from app.models.client import Client
from app.models.document import Document
from app.models.invoice import Invoice
from app.models.project import Project
from app.models.user import User
from app.schemas.client import ClientCreate, ClientOut, ClientUpdate
from app.schemas.common import MessageResponse
from app.schemas.document import (
    ClientDocumentOut,
    ClientDocumentUpdate,
    DocumentFolderSuggestOut,
    DocumentFolderSuggestRequest,
)
from app.schemas.record_360 import Record360View

router = APIRouter(prefix="/clients", tags=["clients"])
settings = get_settings()

PREVIEWABLE_TYPES = {
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
    "image/gif",
    "application/pdf",
}


class SendEmailRequest(BaseModel):
    content: str = Field(min_length=1)
    subject: str | None = None


@router.get("", response_model=list[ClientOut])
async def list_clients(
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Client).where(Client.company_id == current.company_id).order_by(Client.created_at.desc())
    )
    clients = result.scalars().all()
    out: list[ClientOut] = []
    for c in clients:
        out.append(await _enrich_client(db, c))
    return out


@router.post("", response_model=ClientOut, status_code=status.HTTP_201_CREATED)
async def create_client(
    body: ClientCreate,
    current: CurrentUser = Depends(require_permission("manage_leads")),
    db: AsyncSession = Depends(get_db),
):
    await assert_can_add_client(db, current.company_id)
    client = Client(company_id=current.company_id, **body.model_dump())
    db.add(client)
    await db.flush()
    await db.refresh(client)
    await realtime_manager.broadcast(current.company_id, "client", f"Client added: {client.business_name}")
    return await _enrich_client(db, client)


@router.get("/document-folders")
async def list_document_folders(
    current: CurrentUser = Depends(require_staff),
):
    return CLIENT_DOCUMENT_FOLDERS


@router.post("/classify-document", response_model=DocumentFolderSuggestOut)
async def classify_document(
    body: DocumentFolderSuggestRequest,
    current: CurrentUser = Depends(require_staff),
):
    result = suggest_document_folder(body.filename, body.content_type or "")
    return DocumentFolderSuggestOut(**result)


@router.get("/{client_id}", response_model=ClientOut)
async def get_client(
    client_id: UUID,
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    client = await _get_client(db, client_id, current.company_id)
    return await _enrich_client(db, client)


@router.get("/{client_id}/360", response_model=Record360View)
async def get_client_360(
    client_id: UUID,
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    return await build_record_360(db, current.company_id, current.id, "client", client_id)


@router.patch("/{client_id}", response_model=ClientOut)
async def update_client(
    client_id: UUID,
    body: ClientUpdate,
    current: CurrentUser = Depends(require_permission("manage_leads")),
    db: AsyncSession = Depends(get_db),
):
    client = await _get_client(db, client_id, current.company_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(client, k, v)
    await db.flush()
    await db.refresh(client)
    await realtime_manager.broadcast(current.company_id, "client", f"Client updated: {client.business_name}")
    return await _enrich_client(db, client)


@router.delete("/{client_id}", response_model=MessageResponse)
async def delete_client(
    client_id: UUID,
    current: CurrentUser = Depends(require_permission("manage_leads")),
    db: AsyncSession = Depends(get_db),
):
    client = await _get_client(db, client_id, current.company_id)
    inv_count = await db.execute(
        select(func.count()).select_from(Invoice).where(
            Invoice.client_id == client_id,
            Invoice.status.in_(["unpaid", "overdue"]),
        )
    )
    if inv_count.scalar_one() > 0:
        raise HTTPException(status_code=400, detail="Cannot delete client with active unpaid invoices")
    business_name = client.business_name
    await db.delete(client)
    await realtime_manager.broadcast(current.company_id, "client", f"Client removed: {business_name}")
    return MessageResponse(message="Client deleted")


@router.post("/{client_id}/send-email", response_model=MessageResponse)
async def send_client_email(
    client_id: UUID,
    body: SendEmailRequest,
    current: CurrentUser = Depends(require_permission("manage_leads")),
    db: AsyncSession = Depends(get_db),
):
    client = await _get_client(db, client_id, current.company_id)
    if not client.email:
        raise HTTPException(status_code=400, detail="Client has no email address")

    subject, text = split_subject_body(body.content, body.subject or "A message from your agency")

    sent, err = await send_custom_email(client.email, subject, text)
    if not sent:
        raise HTTPException(status_code=502, detail=err or "Email could not be sent")

    if settings.email_enabled:
        return MessageResponse(message=f"Email sent to {client.email}")
    return MessageResponse(message="Email logged (mock — set RESEND_API_KEY to send for real)")


@router.get("/{client_id}/documents", response_model=list[ClientDocumentOut])
async def list_client_documents(
    client_id: UUID,
    folder: str | None = Query(default=None),
    search: str | None = Query(default=None),
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    await _get_client(db, client_id, current.company_id)
    q = select(Document).where(
        Document.client_id == client_id,
        Document.company_id == current.company_id,
        Document.kind == "client_document",
    )
    if folder:
        q = q.where(Document.folder == folder)
    if search:
        q = q.where(Document.filename.ilike(f"%{search.strip()}%"))
    q = q.order_by(Document.folder.asc(), Document.created_at.desc())
    result = await db.execute(q)
    docs = list(result.scalars().all())
    return [await _client_document_out(db, d) for d in docs]


@router.post("/{client_id}/documents", response_model=ClientDocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_client_document(
    client_id: UUID,
    file: UploadFile = File(...),
    folder: str = Query(default="others"),
    current: CurrentUser = Depends(require_permission("manage_leads")),
    db: AsyncSession = Depends(get_db),
):
    client = await _get_client(db, client_id, current.company_id)
    folder_key = folder if folder in VALID_FOLDER_KEYS else "others"
    data = await _read_upload(file)
    content_type = file.content_type or storage.guess_content_type(file.filename or "")
    key = storage.build_key(current.company_id, "clients", file.filename or "file")
    await storage.save(key, data, content_type)

    doc = Document(
        company_id=current.company_id,
        client_id=client.id,
        uploaded_by=current.id,
        filename=file.filename or "file",
        content_type=content_type,
        size=len(data),
        storage_key=key,
        kind="client_document",
        folder=folder_key,
    )
    db.add(doc)
    await db.flush()
    await realtime_manager.broadcast(
        current.company_id, "client", f"Document uploaded for {client.business_name}: {doc.filename}"
    )
    return await _client_document_out(db, doc)


@router.get("/{client_id}/documents/{doc_id}/download")
async def download_client_document(
    client_id: UUID,
    doc_id: UUID,
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    doc = await _get_client_document(db, client_id, doc_id, current.company_id)
    try:
        data = await storage.load(doc.storage_key)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File no longer available") from None
    return Response(
        content=data,
        media_type=doc.content_type,
        headers={"Content-Disposition": f'attachment; filename="{doc.filename}"'},
    )


@router.get("/{client_id}/documents/{doc_id}/preview")
async def preview_client_document(
    client_id: UUID,
    doc_id: UUID,
    current: CurrentUser = Depends(require_staff),
    db: AsyncSession = Depends(get_db),
):
    doc = await _get_client_document(db, client_id, doc_id, current.company_id)
    if doc.content_type not in PREVIEWABLE_TYPES:
        raise HTTPException(status_code=400, detail="This file type cannot be previewed")
    try:
        data = await storage.load(doc.storage_key)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File no longer available") from None
    return Response(
        content=data,
        media_type=doc.content_type,
        headers={"Content-Disposition": f'inline; filename="{doc.filename}"'},
    )


@router.patch("/{client_id}/documents/{doc_id}", response_model=ClientDocumentOut)
async def update_client_document(
    client_id: UUID,
    doc_id: UUID,
    body: ClientDocumentUpdate,
    current: CurrentUser = Depends(require_permission("manage_leads")),
    db: AsyncSession = Depends(get_db),
):
    doc = await _get_client_document(db, client_id, doc_id, current.company_id)
    if body.filename is not None:
        name = body.filename.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Filename cannot be empty")
        doc.filename = name
    if body.folder is not None:
        if body.folder not in VALID_FOLDER_KEYS:
            raise HTTPException(status_code=400, detail="Invalid folder")
        doc.folder = body.folder
    await db.flush()
    return await _client_document_out(db, doc)


@router.delete("/{client_id}/documents/{doc_id}", response_model=MessageResponse)
async def delete_client_document(
    client_id: UUID,
    doc_id: UUID,
    current: CurrentUser = Depends(require_permission("manage_leads")),
    db: AsyncSession = Depends(get_db),
):
    doc = await _get_client_document(db, client_id, doc_id, current.company_id)
    await storage.delete(doc.storage_key)
    await db.delete(doc)
    return MessageResponse(message="Document deleted")


async def _get_client(db: AsyncSession, client_id: UUID, company_id: UUID) -> Client:
    result = await db.execute(select(Client).where(Client.id == client_id, Client.company_id == company_id))
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


async def _enrich_client(db: AsyncSession, client: Client) -> ClientOut:
    proj = await db.execute(
        select(func.count()).select_from(Project).where(
            Project.client_id == client.id, Project.status.in_(["planning", "active", "review"])
        )
    )
    inv = await db.execute(select(func.count()).select_from(Invoice).where(Invoice.client_id == client.id))
    return ClientOut(
        id=client.id,
        company_id=client.company_id,
        assigned_user_id=client.assigned_user_id,
        name=client.name,
        business_name=client.business_name,
        email=client.email,
        phone=client.phone,
        address=client.address,
        gst_number=client.gst_number,
        notes=client.notes,
        created_at=client.created_at,
        active_projects=proj.scalar_one(),
        invoice_count=inv.scalar_one(),
    )


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


def _api_base() -> str:
    return f"{settings.backend_public_url.rstrip('/')}{settings.api_v1_prefix}"


def _client_doc_urls(client_id: UUID, doc_id: UUID, content_type: str) -> tuple[str, str | None]:
    base = _api_base()
    download = f"{base}/clients/{client_id}/documents/{doc_id}/download"
    preview = (
        f"{base}/clients/{client_id}/documents/{doc_id}/preview"
        if content_type in PREVIEWABLE_TYPES
        else None
    )
    return download, preview


async def _creator_name(db: AsyncSession, user_id: UUID | None) -> str | None:
    if not user_id:
        return None
    user = await db.get(User, user_id)
    if not user:
        return None
    return f"{user.first_name} {user.last_name or ''}".strip()


async def _client_document_out(db: AsyncSession, doc: Document) -> ClientDocumentOut:
    download, preview = _client_doc_urls(doc.client_id, doc.id, doc.content_type)
    return ClientDocumentOut(
        id=doc.id,
        client_id=doc.client_id,
        folder=doc.folder,
        folder_label=folder_label(doc.folder),
        filename=doc.filename,
        content_type=doc.content_type,
        size=doc.size,
        uploaded_by_id=doc.uploaded_by,
        uploaded_by_name=await _creator_name(db, doc.uploaded_by),
        uploaded_at=doc.created_at,
        preview_url=preview,
        download_url=download,
        is_previewable=doc.content_type in PREVIEWABLE_TYPES,
    )


async def _get_client_document(
    db: AsyncSession, client_id: UUID, doc_id: UUID, company_id: UUID
) -> Document:
    result = await db.execute(
        select(Document).where(
            Document.id == doc_id,
            Document.client_id == client_id,
            Document.company_id == company_id,
            Document.kind == "client_document",
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc
