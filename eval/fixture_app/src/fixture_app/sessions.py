from __future__ import annotations

from dataclasses import dataclass
import secrets


@dataclass
class Session:
    token: str
    user_id: str
    created_at: int
    expires_at: int
    closed: bool = False


class SessionManager:
    """Manages user authentication sessions with timestamps in integer seconds."""

    def __init__(self, ttl_seconds: int = 3600) -> None:
        self.ttl_seconds = ttl_seconds
        self._sessions: dict[str, Session] = {}

    def create_session(self, user_id: str, now_ts: int) -> Session:
        token = f"sess_{secrets.token_hex(8)}"
        session = Session(
            token=token,
            user_id=user_id,
            created_at=now_ts,
            expires_at=now_ts + self.ttl_seconds,
        )
        self._sessions[token] = session
        return session

    def validate_session(self, token: str | None, now_ts: int) -> Session | None:
        """Returns the Session if active and unexpired."""
        if not token:
            return None
        session = self._sessions.get(token)
        if session is None or session.closed:
            return None
        if now_ts > session.expires_at:
            return None
        return session

    def refresh_session(self, token: str, now_ts: int) -> Session:
        """Extends `expires_at` to `ttl_seconds` after `now_ts`."""
        session = self._sessions.get(token)
        if session is None:
            raise KeyError("Unknown session token")
        session.expires_at = now_ts + self.ttl_seconds
        return session

    def close_session(self, token: str) -> None:
        """Idempotently marks a session closed."""
        session = self._sessions.get(token)
        if session is not None:
            session.closed = True
