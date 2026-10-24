from __future__ import annotations

from fixture_app.models import CartItem, CategoryNode, PromoCode


def calculate_promo_discount(
    items: list[CartItem],
    promo: PromoCode | None
) -> float:
    """Calculates the dollar discount for a cart given an optional PromoCode."""
    if promo is None or not promo.active:
        return 0.0

    raw_subtotal = sum(item.unit_price * item.quantity for item in items)
    if raw_subtotal < promo.min_subtotal:
        return 0.0

    eligible_amount = 0.0
    for item in items:
        if item.bundle_id is not None:
            continue
        eligible_amount += item.unit_price * item.quantity

    discount = round(eligible_amount * (promo.percent_off / 100.0), 2)
    return min(discount, raw_subtotal)

def find_category_multiplier(root: CategoryNode, target_name: str) -> float | None:
    """Searches a category tree for `target_name` and returns its multiplier."""
    if root.name == target_name:
        return root.discount_multiplier
    for child in root.children:
        found = find_category_multiplier(child, target_name)
        if found is not None:
            return found
    return None
