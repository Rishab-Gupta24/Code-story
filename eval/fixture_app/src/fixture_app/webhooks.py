from __future__ import annotations

import hashlib
import hmac
from typing import Any


class WebhookProcessor:
    """Processes incoming payment and shipping webhooks."""

    def __init__(self, signing_secret: str = "whsec_test_secret") -> None:
        self._secret = signing_secret
        self._processed_events: dict[str, dict[str, Any]] = {}
        self.applied_credits: list[tuple[str, float]] = []

    def verify_signature(self, payload_bytes: bytes, signature_header: str) -> bool:
        """Verifies HMAC-SHA256 webhook signature."""
        expected = hmac.new(
            self._secret.encode("utf-8"),
            payload_bytes,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature_header.strip())

    def handle_event(self, event: dict[str, Any]) -> dict[str, Any]:
        """Handles a webhook event payload."""
        event_id = str(event.get("id") or "")
        if not event_id:
            raise ValueError("Webhook event missing 'id'")

        event_type = event.get("type")
        if event_type == "credit.issued":
            user_id = str(event["user_id"])
            amount = float(event["amount"])
            self.applied_credits.append((user_id, amount))

        result = {"event_id": event_id, "status": "processed", "type": event_type}
        self._processed_events[event_id] = result
        return result
