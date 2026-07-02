from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "agencyflow",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.tasks.whatsapp_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_routes={"app.tasks.whatsapp_tasks.*": {"queue": "whatsapp"}},
    task_default_queue="whatsapp",
)
