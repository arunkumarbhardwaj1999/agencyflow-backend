from fastapi import APIRouter, Depends, HTTPException

from app.core.config import get_settings
from app.core.deps import CurrentUser, require_company
from app.core.whatsapp import WhatsAppError, send_text
from app.schemas.integrations import (
    EmailIntegrationStatus,
    IntegrationsStatus,
    WhatsAppIntegrationStatus,
    WhatsAppTestRequest,
    WhatsAppTestResponse,
)

router = APIRouter(prefix="/integrations", tags=["integrations"])
settings = get_settings()


def _require_owner(current: CurrentUser = Depends(require_company)) -> CurrentUser:
    if current.role_name != "owner":
        raise HTTPException(status_code=403, detail="Only workspace owners can manage integrations")
    return current


def _integrations_status() -> IntegrationsStatus:
    return IntegrationsStatus(
        email=EmailIntegrationStatus(
            enabled=settings.email_enabled,
            provider=settings.email_provider_name if settings.email_enabled else "mock",
            from_address=settings.email_from if settings.email_enabled else None,
        ),
        whatsapp=WhatsAppIntegrationStatus(
            enabled=settings.whatsapp_enabled,
            provider="meta" if settings.whatsapp_enabled else "mock",
            token_configured=bool(settings.whatsapp_token),
            phone_number_id_configured=bool(settings.whatsapp_phone_number_id),
            business_account_id=settings.whatsapp_business_account_id or None,
            celery_queue=settings.celery_enabled,
            auto_on_payment=settings.whatsapp_auto_on_payment,
            auto_on_invoice_send=settings.whatsapp_auto_on_invoice_send,
        ),
    )


@router.get("/status", response_model=IntegrationsStatus)
async def get_integrations_status(_: CurrentUser = Depends(_require_owner)):
    return _integrations_status()


@router.post("/whatsapp/test", response_model=WhatsAppTestResponse)
async def test_whatsapp(
    body: WhatsAppTestRequest,
    _: CurrentUser = Depends(_require_owner),
):
    message = (
        "AgencyFlow test — your WhatsApp integration is working. "
        "You can send invoice and payment updates to clients from Finance."
    )
    try:
        result = await send_text(body.phone, message)
    except WhatsAppError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    detail = None
    if result.get("status") == "mock":
        detail = (
            "Mock mode — message logged only. Add WHATSAPP_TOKEN and WHATSAPP_PHONE_NUMBER_ID "
            "to backend .env and restart Docker."
        )

    return WhatsAppTestResponse(
        status=result.get("status", "unknown"),
        phone=result.get("to", body.phone),
        message_id=result.get("message_id"),
        delivery=result.get("delivery", "text"),
        detail=detail,
    )
