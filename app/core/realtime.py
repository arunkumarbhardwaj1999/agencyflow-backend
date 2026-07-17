from collections import defaultdict, deque
from datetime import datetime
from app.core.utc import UTC
from uuid import UUID, uuid4

from fastapi import WebSocket

from app.core.realtime_bus import publish_event


class RealtimeManager:
    def __init__(self) -> None:
        self._connections: dict[str, set[WebSocket]] = defaultdict(set)
        self._recent_events: dict[str, deque[dict]] = defaultdict(lambda: deque(maxlen=50))

    async def connect(self, company_id: UUID, websocket: WebSocket) -> None:
        key = str(company_id)
        await websocket.accept()
        self._connections[key].add(websocket)

    def disconnect(self, company_id: UUID, websocket: WebSocket) -> None:
        key = str(company_id)
        if key in self._connections:
            self._connections[key].discard(websocket)
            if not self._connections[key]:
                del self._connections[key]

    async def broadcast(self, company_id: UUID, event_type: str, message: str) -> None:
        payload = {
            "id": f"{event_type}-{uuid4()}",
            "type": event_type,
            "message": message,
            "created_at": datetime.now(UTC).isoformat(),
        }
        key = str(company_id)
        self._recent_events[key].appendleft(payload)
        await self._send_local(key, payload)
        await publish_event(key, payload)

    async def relay(self, company_id: str, payload: dict) -> None:
        """Deliver an event received from Redis to local WebSocket clients."""
        key = str(company_id)
        self._recent_events[key].appendleft(payload)
        await self._send_local(key, payload)

    async def _send_local(self, key: str, payload: dict) -> None:
        dead_connections: list[WebSocket] = []
        for ws in self._connections.get(key, set()):
            try:
                await ws.send_json(payload)
            except Exception:
                dead_connections.append(ws)
        if dead_connections:
            company_id = UUID(key)
            for ws in dead_connections:
                self.disconnect(company_id, ws)

    def recent(self, company_id: UUID, limit: int = 5) -> list[dict]:
        return list(self._recent_events[str(company_id)])[:limit]


realtime_manager = RealtimeManager()
