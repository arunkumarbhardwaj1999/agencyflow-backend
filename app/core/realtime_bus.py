"""Redis pub/sub bus for cross-instance WebSocket broadcasts."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger("agencyflow.realtime")
settings = get_settings()

_redis = None
_subscriber_task: asyncio.Task | None = None


async def get_redis():
    global _redis
    if _redis is not None:
        return _redis
    if not settings.redis_url:
        return None
    try:
        import redis.asyncio as aioredis

        _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
        await _redis.ping()
        return _redis
    except Exception as exc:
        logger.warning("Redis unavailable for realtime bus: %s", exc)
        return None


async def publish_event(company_id: str, payload: dict[str, Any]) -> None:
    client = await get_redis()
    if not client:
        return
    try:
        await client.publish(f"ws:{company_id}", json.dumps(payload))
    except Exception as exc:
        logger.warning("Redis publish failed: %s", exc)


async def start_subscriber(on_message) -> None:
    """Subscribe to ws:* channels and call on_message(company_id, payload)."""
    global _subscriber_task
    if _subscriber_task and not _subscriber_task.done():
        return

    client = await get_redis()
    if not client:
        return

    async def _listen():
        pubsub = client.pubsub()
        await pubsub.psubscribe("ws:*")
        logger.info("Realtime Redis subscriber started")
        try:
            async for raw in pubsub.listen():
                if raw["type"] != "pmessage":
                    continue
                channel = raw["channel"]
                company_id = channel.split(":", 1)[-1]
                try:
                    payload = json.loads(raw["data"])
                except json.JSONDecodeError:
                    continue
                await on_message(company_id, payload)
        except asyncio.CancelledError:
            await pubsub.punsubscribe("ws:*")
            raise
        except Exception as exc:
            logger.warning("Realtime subscriber error: %s", exc)

    _subscriber_task = asyncio.create_task(_listen())


async def stop_subscriber() -> None:
    global _subscriber_task, _redis
    if _subscriber_task and not _subscriber_task.done():
        _subscriber_task.cancel()
        try:
            await _subscriber_task
        except asyncio.CancelledError:
            pass
    _subscriber_task = None
    if _redis:
        await _redis.aclose()
        _redis = None
