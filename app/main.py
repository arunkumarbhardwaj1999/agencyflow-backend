from contextlib import asynccontextmanager

from uuid import UUID

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.limiter import limiter
from app.core.realtime import realtime_manager
from app.core.realtime_bus import start_subscriber, stop_subscriber
from app.core.security import decode_token

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    await start_subscriber(realtime_manager.relay)
    yield
    await stop_subscriber()


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
@limiter.limit(settings.rate_limit)
async def health(request: Request):
    return {
        "status": "ok",
        "app": settings.app_name,
        "integrations": {
            "email": {
                "enabled": settings.email_enabled,
                "provider": settings.email_provider_name,
                "from": settings.email_from if settings.email_enabled else None,
                "hint": settings.email_config_hint(),
            },
            "whatsapp": {
                "enabled": settings.whatsapp_enabled,
                "provider": "meta" if settings.whatsapp_enabled else "mock",
                "celery_queue": settings.celery_enabled,
            },
            "sms": {
                "enabled": settings.sms_enabled,
                "provider": settings.sms_provider or "mock",
            },
            "payments": {
                "mock": settings.payments_mock,
                "razorpay": settings.razorpay_enabled,
                "stripe": settings.stripe_enabled,
            },
            "ai": {"enabled": settings.ai_enabled, "provider": settings.ai_provider},
        },
    }


@app.websocket("/ws/dashboard/{company_id}")
async def dashboard_ws(websocket: WebSocket, company_id: UUID, token: str):
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            await websocket.close(code=1008, reason="Invalid token type")
            return
        if payload.get("company_id") != str(company_id):
            await websocket.close(code=1008, reason="Token workspace mismatch")
            return
    except Exception:
        await websocket.close(code=1008, reason="Invalid token")
        return

    await realtime_manager.connect(company_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        realtime_manager.disconnect(company_id, websocket)


app.include_router(api_router, prefix=settings.api_v1_prefix)
