from fastapi import APIRouter

from app.api.v1 import auth, clients, dashboard, leads, projects, tasks

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(leads.router)
api_router.include_router(clients.router)
api_router.include_router(projects.router)
api_router.include_router(tasks.router)
api_router.include_router(dashboard.router)
