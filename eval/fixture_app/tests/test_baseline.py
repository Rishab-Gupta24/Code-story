from __future__ import annotations

from fixture_app.webhooks import WebhookProcessor
from fixture_app.cache import ProfileCache
from fixture_app.checkout import process_checkout
from fixture_app.cart import Cart
from fixture_app.inventory import InventoryStore
from fixture_app.models import (
    CategoryNode,
    OrderStatus,
    PromoCode,
    User,
)
from fixture_app.orders import OrderRepository, average_order_value
from fixture_app.sessions import SessionManager
from fixture_app.permissions import can_modify_order, check_external_policy
from fixture_app.promo import calculate_promo_discount, find_category_multiplier
from fixture_app.reporting import summarize_daily_revenue


def test_cart_and_successful_checkout() -> None:
    inv = InventoryStore({"SKU-1": 10})
    cart = Cart(user_id="u1")
    cart.add_item("SKU-1", "Mechanical Keyboard", 100.0, 2)
    user = User(user_id="u1", email="u1@example.com")

    order = process_checkout(
        cart=cart,
        user=user,
        inventory=inv,
        charge_fn=lambda u, total: f"tx_{int(total)}",
        tax_rate=0.10,
    )
    assert order.status == OrderStatus.PAID
    assert order.subtotal == 200.0
    assert inv.available("SKU-1") == 8
    assert inv.reserved("SKU-1") == 0


def test_promo_basic_percentage() -> None:
    cart = Cart(user_id="u1")
    cart.add_item("SKU-1", "Mouse", 50.0, 2)
    promo = PromoCode(code="SAVE10", percent_off=10.0)
    assert calculate_promo_discount(cart.items, promo) == 10.0


def test_category_tree_lookup() -> None:
    tree = CategoryNode(
        "root",
        1.0,
        [CategoryNode("electronics", 0.9, [CategoryNode("audio", 0.85)])],
    )
    assert find_category_multiplier(tree, "audio") == 0.85
    assert find_category_multiplier(tree, "missing") is None


def test_orders_first_page_and_average() -> None:
    repo = OrderRepository()
    inv = InventoryStore({"SKU-1": 20})
    user = User(user_id="u1", email="u1@example.com")

    for idx in range(3):
        c = Cart(user_id="u1")
        c.add_item("SKU-1", "Item", 25.0, 1)
        order = process_checkout(
            c,
            user,
            inv,
            charge_fn=lambda u, t: "tx",
            order_id=f"ORD-{idx}",
            now_ts=1000 + idx,
        )
        repo.save(order)

    page1 = repo.list_for_user("u1", page=1, page_size=2)
    assert [o.order_id for o in page1] == ["ORD-2", "ORD-1"]
    assert average_order_value(page1) == 27.0


def test_sessions_and_close() -> None:
    mgr = SessionManager(ttl_seconds=60)
    sess = mgr.create_session("u1", now_ts=1000)
    assert mgr.validate_session(sess.token, now_ts=1030) is not None
    mgr.close_session(sess.token)
    mgr.close_session(sess.token)  # Idempotent second call
    assert mgr.validate_session(sess.token, now_ts=1030) is None


def test_permissions_and_webhooks_and_cache() -> None:
    admin = User(user_id="admin1", email="a@example.com", role="admin")
    inv = InventoryStore({"SKU-1": 5})
    cart = Cart(user_id="u1")
    cart.add_item("SKU-1", "Book", 20.0, 1)
    order = process_checkout(cart, admin, inv, charge_fn=lambda u, t: "tx")

    assert can_modify_order(admin, order) is True
    assert check_external_policy(admin, "refund", lambda uid, act: True) is True

    wp = WebhookProcessor()
    res = wp.handle_event({"id": "evt_1", "type": "credit.issued", "user_id": "u1", "amount": 15.0})
    assert res["status"] == "processed"
    assert wp.applied_credits == [("u1", 15.0)]

    cache = ProfileCache(ttl_seconds=300)
    cache.put_user(User(user_id="u1", email="old@example.com"))
    profile = cache.get_profile("u1", now_ts=100)
    assert profile is not None and profile.email == "old@example.com"

    summary = summarize_daily_revenue([order])
    assert len(summary) == 1


def test_restock_adds_units() -> None:
    from fixture_app.restock import restock

    inv = InventoryStore({"SKU-1": 2})
    assert restock(inv, "SKU-1", 3) == 5


def test_call_with_retries_makes_exactly_max_attempts() -> None:
    import pytest

    from fixture_app.models import GatewayTimeoutError
    from fixture_app.retry import call_with_retries

    calls = []

    def always_times_out() -> str:
        calls.append(1)
        raise GatewayTimeoutError("timeout")

    with pytest.raises(GatewayTimeoutError):
        call_with_retries(always_times_out, max_attempts=3)
    assert len(calls) == 3
