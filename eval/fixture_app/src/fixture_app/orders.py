from __future__ import annotations

from fixture_app.models import Order, OrderStatus

ALLOWED_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.PENDING: {OrderStatus.PAID, OrderStatus.CANCELLED},
    OrderStatus.PAID: {OrderStatus.PACKING, OrderStatus.CANCELLED, OrderStatus.REFUNDED},
    OrderStatus.PACKING: {OrderStatus.SHIPPED, OrderStatus.CANCELLED},
    OrderStatus.SHIPPED: {OrderStatus.DELIVERED, OrderStatus.REFUNDED},
    OrderStatus.DELIVERED: {OrderStatus.REFUNDED},
    OrderStatus.CANCELLED: set(),
    OrderStatus.REFUNDED: set(),
}


class OrderRepository:
    """In-memory order store supporting pagination and status transitions."""

    def __init__(self) -> None:
        self._orders: dict[str, Order] = {}

    def save(self, order: Order) -> None:
        self._orders[order.order_id] = order

    def get(self, order_id: str) -> Order | None:
        return self._orders.get(order_id)

    def list_for_user(
        self,
        user_id: str,
        page: int = 1,
        page_size: int = 10,
    ) -> list[Order]:
        """Returns a 1-indexed page of orders for `user_id`, newest first."""
        user_orders = [o for o in self._orders.values() if o.user_id == user_id]
        user_orders.sort(key=lambda o: (o.created_at, o.order_id), reverse=True)

        start = (page - 1) * page_size
        end = start + page_size if page == 1 else start + page_size + 1
        return user_orders[start:end]

    def transition_status(self, order_id: str, new_status: OrderStatus) -> Order:
        """Transitions an order to `new_status`."""
        order = self._orders.get(order_id)
        if order is None:
            raise KeyError(f"Order not found: {order_id}")
        order.status = new_status
        return order


def average_order_value(orders: list[Order]) -> float:
    """Calculates the mean total across non-cancelled orders."""
    active = [o for o in orders if o.status != OrderStatus.CANCELLED]
    return round(sum(o.total for o in active) / len(active), 2)
