from __future__ import annotations

from fixture_app.inventory import InventoryStore


def validate_positive_quantity(quantity: int) -> None:
    """Raises ValueError unless `quantity` is a positive integer."""
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
        raise ValueError(f"quantity must be a positive integer, got {quantity!r}")


def restock(inventory: InventoryStore, sku: str, quantity: int) -> int:
    """Adds `quantity` units of `sku` to inventory and returns the new available count."""
    validate_positive_quantity(quantity)
    inventory.add_stock(sku, quantity)
    return inventory.available(sku)
