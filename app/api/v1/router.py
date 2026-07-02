from fastapi import APIRouter

from app.api.v1 import (
    ai,
    auth,
    clients,
    dashboard,
    files,
    invoices,
    leads,
    payments,
    portal,
    projects,
    tasks,
    users,
    whatsapp,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(leads.router)
api_router.include_router(clients.router)
api_router.include_router(projects.router)
api_router.include_router(tasks.router)
api_router.include_router(dashboard.router)
api_router.include_router(invoices.router)
api_router.include_router(payments.router)
api_router.include_router(portal.router)
api_router.include_router(users.router)
api_router.include_router(files.router)
api_router.include_router(whatsapp.router)
api_router.include_router(ai.router)
