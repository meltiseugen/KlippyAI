from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Lock
from uuid import uuid4


@dataclass(slots=True)
class UiSession:
    session_id: str
    expires_at: datetime


class InMemorySessionStore:
    def __init__(self, ttl_seconds: int) -> None:
        self._ttl_seconds = ttl_seconds
        self._sessions: dict[str, UiSession] = {}
        self._lock = Lock()

    def create(self) -> UiSession:
        session = UiSession(
            session_id=str(uuid4()),
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=self._ttl_seconds),
        )
        with self._lock:
            self._purge_expired_locked()
            self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str) -> UiSession | None:
        with self._lock:
            self._purge_expired_locked()
            return self._sessions.get(session_id)

    def exists(self, session_id: str) -> bool:
        return self.get(session_id) is not None

    def _purge_expired_locked(self) -> None:
        now = datetime.now(timezone.utc)
        expired = [key for key, session in self._sessions.items() if session.expires_at <= now]
        for key in expired:
            self._sessions.pop(key, None)

