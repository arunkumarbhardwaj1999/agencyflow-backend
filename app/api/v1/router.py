from fastapi import APIRouter

from app.api.v1 import (
    ai,
    auth,
    automations,
    calendar,
    client_portal_staff,
    clients,
    communications,
    contracts,
    deals,
    files,
    hr,
    integrations,
    invoices,
    leads,
    payments,
    portal,
    projects,
    proposals,
    records,
    reports,
    tasks,
    time_tracking,
    users,
    whatsapp,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(leads.router)
api_router.include_router(deals.router)
api_router.include_router(clients.router)
api_router.include_router(projects.router)
api_router.include_router(records.router)
api_router.include_router(tasks.router)
api_router.include_router(time_tracking.router)
api_router.include_router(reports.router)
api_router.include_router(calendar.router)
api_router.include_router(communications.router)
api_router.include_router(integrations.router)
api_router.include_router(invoices.router)
api_router.include_router(proposals.router)
api_router.include_router(contracts.router)
api_router.include_router(hr.router)
api_router.include_router(automations.router)
api_router.include_router(payments.router)
api_router.include_router(portal.router)
api_router.include_router(client_portal_staff.router)
api_router.include_router(users.router)
api_router.include_router(files.router)
api_router.include_router(whatsapp.router)
api_router.include_router(ai.router)
