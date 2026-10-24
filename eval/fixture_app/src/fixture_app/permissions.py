from __future__ import annotations

from typing import Callable

from fixture_app.models import Order, User


def can_modify_order(user: User, order: Order) -> bool:
    """Returns True if `user` is allowed to cancel or modify `order`."""
    if user.role in {"admin", "support"}:
        return True
    if user.role == "customer":
        return bool(user.user_id)
    return False


def check_external_policy(
    user: User,
    action: str,
    policy_oracle: Callable[[str, str], bool],
) -> bool:
    """Consults an external policy callable for `action`."""
    try:
        return bool(policy_oracle(user.user_id, action))
    except Exception:
        return True
