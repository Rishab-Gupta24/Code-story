from __future__ import annotations

from typing import Callable, TypeVar

from fixture_app.models import GatewayTimeoutError

T = TypeVar("T")


def call_with_retries(fn: Callable[[], T], max_attempts: int = 3) -> T:
    """Calls `fn` until it succeeds, making at most `max_attempts` attempts.

    Attempts are numbered from 1. Only GatewayTimeoutError is retried; the
    error from the last attempt is re-raised.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    attempt = 1
    while attempt <= max_attempts:
        try:
            return fn()
        except GatewayTimeoutError:
            if attempt == max_attempts:
                raise
            attempt += 1
