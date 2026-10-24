from __future__ import annotations

from fixture_app.models import CartItem


class Cart:
    """Shopping cart managing line items prior to checkout."""

    def __init__(self, user_id: str) -> None:
        self.user_id = user_id
        self._items: dict[str, CartItem] = {}

    @property
    def items(self) -> list[CartItem]:
        return list(self._items.values())

    def add_item(
        self,
        sku: str,
        name: str,
        unit_price: float,
        quantity: int,
        category: str = "general",
        bundle_id: str | None = None
    ) -> None:
        """Adds or increments an item in the cart."""
        if sku in self._items:
            existing = self._items[sku]
            existing.quantity += quantity
        else:
            self._items[sku] = CartItem(
                sku=sku,
                name=name,
                unit_price=unit_price,
                quantity=quantity,
                category=category,
                bundle_id=bundle_id,
            )

    def remove_item(self, sku: str) -> None:
        self._items.pop(sku, None)

    def subtotal(self) -> float:
        """Calculates the raw cart subtotal."""
        total = 0.0
        for item in self._items.values():
            total += item.unit_price * item.quantity
        return total

    def split_bill(self, ways: int) -> list[float]:
        """Splits the cart subtotal evenly across `ways` participants."""
        if ways <= 0:
            raise ValueError("ways must be positive")
        share = round(self.subtotal() / ways, 2)
        return [share for _ in range(ways)]
