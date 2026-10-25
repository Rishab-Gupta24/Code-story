"""Targeted failure-path checks for the Phase 5 fix cases (R01-R04).

The fixture's baseline suite covers only the success paths, so it can't show
that a fix works. These checks exercise the seeded failure path directly.

Usage: python phase5_regression_checks.py <case_id> <run_folder> [<run_folder> ...]

Each folder is checked in its own subprocess with <run_folder>/src on the
import path. Prints one PASS/FAIL line per folder; exit code 1 if any fail.
Run it against the unfixed eval/fixture_app as a control: it should FAIL.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

CHECKS = {
    # R01 and R03: a failed charge must release the reservation and re-raise.
    "R01": """
from fixture_app.cart import Cart
from fixture_app.checkout import process_checkout
from fixture_app.inventory import InventoryStore
from fixture_app.models import GatewayTimeoutError, PaymentError, User

for exc in (PaymentError, GatewayTimeoutError):
    inv = InventoryStore({"SKU-1": 10})
    cart = Cart(user_id="u1")
    cart.add_item("SKU-1", "Keyboard", 100.0, 2)

    def charge(u, total):
        raise exc("declined")

    try:
        process_checkout(cart, User(user_id="u1", email="u1@example.com"), inv, charge)
    except exc:
        pass
    else:
        raise AssertionError(f"{exc.__name__} was not re-raised")
    assert inv.available("SKU-1") == 10, (exc.__name__, "available", inv.available("SKU-1"))
    assert inv.reserved("SKU-1") == 0, (exc.__name__, "reserved", inv.reserved("SKU-1"))
""",
    # R02: no active orders must give 0.0, not ZeroDivisionError.
    "R02": """
from fixture_app.cart import Cart
from fixture_app.checkout import process_checkout
from fixture_app.inventory import InventoryStore
from fixture_app.models import OrderStatus, User
from fixture_app.orders import average_order_value

assert average_order_value([]) == 0.0

cart = Cart(user_id="u1")
cart.add_item("SKU-1", "Item", 25.0, 1)
order = process_checkout(
    cart, User(user_id="u1", email="u1@example.com"), InventoryStore({"SKU-1": 5}),
    charge_fn=lambda u, t: "tx",
)
order.status = OrderStatus.CANCELLED
assert average_order_value([order]) == 0.0
""",
    # R04: an oracle exception must deny (fail closed); a normal answer passes through.
    "R04": """
from fixture_app.models import User
from fixture_app.permissions import check_external_policy

user = User(user_id="u1", email="u1@example.com")

def broken(user_id, action):
    raise RuntimeError("policy service down")

assert check_external_policy(user, "refund", broken) is False
assert check_external_policy(user, "refund", lambda u, a: True) is True
assert check_external_policy(user, "refund", lambda u, a: False) is False
""",
}
CHECKS["R03"] = CHECKS["R01"]


def main() -> int:
    case_id, folders = sys.argv[1], sys.argv[2:]
    failed = False
    for folder in folders:
        src = str(Path(folder) / "src")
        code = f"import sys; sys.path.insert(0, {src!r})\n" + CHECKS[case_id]
        proc = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True)
        if proc.returncode == 0:
            print(f"PASS {case_id} {folder}")
        else:
            failed = True
            last = (proc.stderr.strip().splitlines() or ["no output"])[-1]
            print(f"FAIL {case_id} {folder}: {last}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
