"""Celery tasks for async WhatsApp delivery."""

from __future__ import annotations

import asyncio
from uuid import UUID

from app.celery_app import celery_app
from app.services.whatsapp_service import deliver_whatsapp


@celery_app.task(name="whatsapp.send", bind=True, max_retries=3, default_retry_delay=30)
def send_whatsapp_task(
    self,
    company_id: str,
    client_id: str | None,
    phone: str,
    message: str,
    template_key: str | None = None,
    params: dict | None = None,
    use_template: bool = True,
) -> dict:
    try:
        log = asyncio.run(
            deliver_whatsapp(
                company_id=UUID(company_id),
                client_id=UUID(client_id) if client_id else None,
                phone=phone,
                message=message,
                template_key=template_key,
                params=params,
                use_template=use_template,
            )
        )
        return {"log_id": str(log.id), "status": log.status}
    except Exception as exc:
        raise self.retry(exc=exc) from exc
