from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PaymentError(Exception):
    """Raised when a payment gateway charge fails."""


class GatewayTimeoutError(PaymentError):
    """Raised when the payment gateway does not respond in time."""


class InsufficientStockError(Exception):
    """Raised when requested inventory exceeds available units."""


class OrderStatus(str, Enum):
    PENDING = "pending"
    PAID = "paid"
    PACKING = "packing"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


@dataclass
class CartItem:
    sku: str
    name: str
    unit_price: float
    quantity: int
    category: str = "general"
    bundle_id: str | None = None


@dataclass
class PromoCode:
    code: str
    percent_off: float
    max_discount: float | None = None
    min_subtotal: float = 0.0
    applies_to_bundles: bool = True
    active: bool = True


@dataclass
class User:
    user_id: str
    email: str
    role: str = "customer"  # "customer", "support", "admin"
    org_id: str | None = None
    loyalty_points: int = 0


@dataclass
class Order:
    order_id: str
    user_id: str
    items: list[CartItem]
    subtotal: float
    discount: float
    tax: float
    total: float
    status: OrderStatus = OrderStatus.PENDING
    created_at: int = 0
    idempotency_key: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CategoryNode:
    name: str
    discount_multiplier: float = 1.0
    children: list[CategoryNode] = field(default_factory=list)
