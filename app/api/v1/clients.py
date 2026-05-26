from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import CurrentUser, require_company, require_permission
from app.db.session import get_db
from app.models.client import Client
from app.models.invoice import Invoice
from app.models.project import Project
from app.schemas.client import ClientCreate, ClientOut, ClientUpdate
from app.schemas.common import MessageResponse

router = APIRouter(prefix="/clients", tags=["clients"])


@router.get("", response_model=list[ClientOut])
async def list_clients(
    current: CurrentUser = Depends(require_company),
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
    client = Client(company_id=current.company_id, **body.model_dump())
    db.add(client)
    await db.flush()
    await db.refresh(client)
    return await _enrich_client(db, client)


@router.get("/{client_id}", response_model=ClientOut)
async def get_client(
    client_id: UUID,
    current: CurrentUser = Depends(require_company),
    db: AsyncSession = Depends(get_db),
):
    client = await _get_client(db, client_id, current.company_id)
    return await _enrich_client(db, client)


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
    await db.delete(client)
    return MessageResponse(message="Client deleted")


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
