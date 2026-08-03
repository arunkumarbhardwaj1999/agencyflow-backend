from contextlib import asynccontextmanager
import logging

from uuid import UUID

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.limiter import limiter
from app.core.realtime import realtime_manager
from app.core.realtime_bus import start_subscriber, stop_subscriber
from app.core.security import decode_token

settings = get_settings()
logger = logging.getLogger("agencyflow")

if not logging.getLogger().handlers:
    logging.basicConfig(
        level=logging.DEBUG if settings.debug else logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


def _assert_production_safe() -> None:
    """Fail fast only in production; warn for other non-debug insecure defaults."""
    env = (settings.environment or "").strip().lower()
    weak_secret = settings.secret_key in ("", "dev-secret-change-in-production")
    if env in ("production", "prod") and weak_secret:
        raise RuntimeError(
            "SECRET_KEY must be set to a strong unique value when ENVIRONMENT is production."
        )
    if not settings.debug and weak_secret:
        logger.warning(
            "Using the default SECRET_KEY with DEBUG disabled. Set a unique SECRET_KEY before go-live."
        )
    if env in ("production", "prod") and settings.payments_mock:
        logger.warning(
            "PAYMENTS_MOCK is enabled in production — payment links will not use live gateways."
        )


@asynccontextmanager
async def lifespan(_: FastAPI):
    _assert_production_safe()
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


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Something went wrong on our side. Please try again shortly."},
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
@limiter.limit(settings.rate_limit)
async def health(request: Request):
    payload: dict = {"status": "ok", "app": settings.app_name}
    if settings.debug:
        payload["integrations"] = {
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
        }
    return payload


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
