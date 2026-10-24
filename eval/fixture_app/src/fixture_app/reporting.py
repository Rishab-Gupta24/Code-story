from __future__ import annotations

from typing import Any

from fixture_app.models import Order


def summarize_daily_revenue(orders: list[Order]) -> dict[str, float]:
    """Groups order totals by integer day bucket (`created_at // 86400`)."""
    buckets: dict[str, float] = {}
    for order in orders:
        day_key = f"day_{order.created_at // 86400}"
        buckets[day_key] = round(buckets.get(day_key, 0.0) + order.total, 2)
    return buckets


def export_orders_to_warehouse(orders: list[Order], db_conn: Any) -> int:
    """Writes order rows into an external SQL warehouse connection."""
    cursor = db_conn.cursor()
    written = 0
    for order in orders:
        cursor.execute(
            "INSERT INTO warehouse_orders (order_id, user_id, total, status) VALUES (?, ?, ?, ?)",
            (order.order_id, order.user_id, order.total, order.status.value),
        )
        written += 1
    db_conn.commit()
    return written
