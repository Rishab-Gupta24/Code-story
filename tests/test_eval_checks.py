"""Guards eval/phase5_regression_checks.py in CI.

The Phase 5 run folders live outside the repo, so CI can't recheck the saved
fixes. Instead this verifies the checks still mean something: each one must
fail on the unfixed fixture and pass once a reference fix is applied.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "eval" / "phase5_regression_checks.py"
FIXTURE = REPO / "eval" / "fixture_app"

# Reference fixes: (file, old, new), one exact replacement each.
REFERENCE_FIXES = {
    "R01": (
        "src/fixture_app/checkout.py",
        "    tx_id = charge_fn(user, total)\n",
        "    try:\n"
        "        tx_id = charge_fn(user, total)\n"
        "    except PaymentError:\n"
        "        inventory.release_stock(cart.items)\n"
        "        raise\n",
    ),
    "R02": (
        "src/fixture_app/orders.py",
        "    active = [o for o in orders if o.status != OrderStatus.CANCELLED]\n",
        "    active = [o for o in orders if o.status != OrderStatus.CANCELLED]\n"
        "    if not active:\n"
        "        return 0.0\n",
    ),
    "R04": (
        "src/fixture_app/permissions.py",
        "    except Exception:\n        return True\n",
        "    except Exception:\n        return False\n",
    ),
}


def run_check(case_id: str, folder: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), case_id, str(folder)],
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize("case_id", ["R01", "R02", "R03", "R04"])
def test_check_fails_on_unfixed_fixture(case_id: str) -> None:
    result = run_check(case_id, FIXTURE)
    assert result.returncode == 1, result.stdout + result.stderr
    assert result.stdout.startswith(f"FAIL {case_id}")


@pytest.mark.parametrize("case_id", ["R01", "R02", "R03", "R04"])
def test_check_passes_with_reference_fix(case_id: str, tmp_path: Path) -> None:
    copy = tmp_path / "fixture_app"
    shutil.copytree(FIXTURE / "src", copy / "src")
    rel, old, new = REFERENCE_FIXES["R01" if case_id == "R03" else case_id]
    path = copy / rel
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1
    path.write_text(text.replace(old, new), encoding="utf-8")

    result = run_check(case_id, copy)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.startswith(f"PASS {case_id}")
