from __future__ import annotations

from dataclasses import replace

from fixture_app.models import User


class ProfileCache:
    """In-memory TTL cache sitting in front of a primary user directory."""

    def __init__(self, ttl_seconds: int = 300) -> None:
        self.ttl_seconds = ttl_seconds
        self._backing_store: dict[str, User] = {}
        self._cache: dict[str, tuple[User, int]] = {}

    def put_user(self, user: User) -> None:
        self._backing_store[user.user_id] = replace(user)

    def get_profile(self, user_id: str, now_ts: int) -> User | None:
        cached = self._cache.get(user_id)
        if cached is not None:
            user, expires_at = cached
            if now_ts < expires_at:
                return replace(user)
            del self._cache[user_id]

        stored = self._backing_store.get(user_id)
        if stored is None:
            return None
        self._cache[user_id] = (replace(stored), now_ts + self.ttl_seconds)
        return replace(stored)

    def update_email(self, user_id: str, new_email: str) -> User:
        """Updates a user's email in the backing store."""
        if user_id not in self._backing_store:
            raise KeyError(f"Unknown user: {user_id}")
        user = self._backing_store[user_id]
        user.email = new_email
        return replace(user)
