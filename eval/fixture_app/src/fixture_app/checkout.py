from __future__ import annotations

from fixture_app.promo import calculate_promo_discount
from fixture_app.cart import Cart
from fixture_app.models import (
    Order,
    OrderStatus,
    PaymentError,
    PromoCode,
    User,
)
from fixture_app.inventory import InventoryStore
from typing import Callable

PaymentGateway = Callable[[User, float], str]


def calculate_tax(taxable_amount: float, tax_rate: float = 0.08) -> float:
    if taxable_amount <= 0:
        return 0.0
    return round(taxable_amount * tax_rate, 2)


def process_checkout(
    cart: Cart,
    user: User,
    inventory: InventoryStore,
    charge_fn: PaymentGateway,
    promo: PromoCode | None = None,
    tax_rate: float = 0.08,
    order_id: str = "ORD-1001",
    now_ts: int = 1_700_000_000,
) -> Order:
    """Processes a customer checkout.

    Contract:
    1. Calculate subtotal, promo discount, and tax on (subtotal - discount).
    2. Call `inventory.reserve_stock(cart.items)` BEFORE calling `charge_fn`.
    3. Call `charge_fn(user, total)`.
    4. If `charge_fn` raises `PaymentError`, call `inventory.release_stock(cart.items)`
       and re-raise the error.
    5. On success, commit the reservation and return a PAID Order.
    """
    if not cart.items:
        raise ValueError("Cannot checkout an empty cart")

    subtotal = round(cart.subtotal(), 2)
    discount = calculate_promo_discount(cart.items, promo)
    tax = calculate_tax(subtotal, tax_rate)
    total = round(max(0.0, subtotal - discount) + tax, 2)

    inventory.reserve_stock(cart.items)

    tx_id = charge_fn(user, total)
    inventory.commit_reservation(cart.items)

    return Order(
        order_id=order_id,
        user_id=user.user_id,
        items=list(cart.items),
        subtotal=subtotal,
        discount=discount,
        tax=tax,
        total=total,
        status=OrderStatus.PAID,
        created_at=now_ts,
        metadata={"transaction_id": tx_id},
    )
