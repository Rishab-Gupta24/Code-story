from __future__ import annotations

from fixture_app.models import CartItem, InsufficientStockError


class InventoryStore:
    """In-memory stock and reservation ledger."""

    def __init__(self, initial_stock: dict[str, int] | None = None) -> None:
        self._available: dict[str, int] = dict(initial_stock or {})
        self._reserved: dict[str, int] = {sku: 0 for sku in self._available}

    def available(self, sku: str) -> int:
        return self._available.get(sku, 0)

    def reserved(self, sku: str) -> int:
        return self._reserved.get(sku, 0)

    def add_stock(self, sku: str, units: int) -> None:
        if units < 0:
            raise ValueError("units must be non-negative")
        self._available[sku] = self._available.get(sku, 0) + units
        self._reserved.setdefault(sku, 0)

    def reserve_stock(self, items: list[CartItem]) -> None:
        """Reserves stock for each item in the list."""
        for item in items:
            avail = self._available.get(item.sku, 0)
            if item.quantity > avail:
                raise InsufficientStockError(
                    f"SKU {item.sku} requires {item.quantity}, only {avail} available"
                )
            self._available[item.sku] = avail - item.quantity
            self._reserved[item.sku] = self._reserved.get(item.sku, 0) + item.quantity

    def release_stock(self, items: list[CartItem]) -> None:
        """Releases previously reserved stock back to available inventory."""
        for item in items:
            current_reserved = self._reserved.get(item.sku, 0)
            release_qty = min(current_reserved, item.quantity)
            self._reserved[item.sku] = current_reserved - release_qty
            self._available[item.sku] = self._available.get(item.sku, 0) + release_qty

    def commit_reservation(self, items: list[CartItem]) -> None:
        """Finalizes reservation after payment succeeds."""
        for item in items:
            current_reserved = self._reserved.get(item.sku, 0)
            commit_qty = min(current_reserved, item.quantity)
            self._reserved[item.sku] = current_reserved - commit_qty
