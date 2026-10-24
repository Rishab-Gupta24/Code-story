"""Phase 2 test suite for retrieval, parser recovery, and drift (see tasks.md)."""

from __future__ import annotations

from pathlib import Path

import pytest

from code_story import server
from code_story.log import LOG_FILENAME, CodeStoryValidationError, record_change_entry
from code_story.review import (
    DRIFT_NOTE,
    EXCERPT_MODIFIED_OR_REMOVED,
    FILE_MISSING,
    FILE_MODIFIED_EXCERPT_INTACT,
    FILE_MODIFIED_NO_EXCERPT,
    UNCHANGED,
    get_change_entry,
    list_change_entries,
    parse_log,
)

CHECKOUT = (
    "def checkout(cart, user):\n"
    "    total = apply_promo(cart, user.promo_code)\n"
    "    reserve_stock(cart.items)\n"
    "    charge(user, total)\n"
)
EXCERPT = "    reserve_stock(cart.items)\n    charge(user, total)"


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    (root / "src" / "checkout.py").write_text(CHECKOUT, encoding="utf-8")
    (root / "src" / "promo.py").write_text("def apply_promo(c, code):\n    return 1\n", encoding="utf-8")
    (root / "src" / "stock.py").write_text("def reserve_stock(items):\n    pass\n", encoding="utf-8")
    return root


def _record(root: Path, summary: str = "Reserve then charge", **overrides: object) -> str:
    kwargs: dict[str, object] = dict(
        project_root=str(root),
        summary=summary,
        explanation="Reserves stock and charges the card.",
        reason="Checkout flow.",
        files=["src/checkout.py"],
        code_excerpt=EXCERPT,
        checks="Unit tests passed.",
        review_question="Is stock released if charge() fails?",
        code_language="python",
    )
    kwargs.update(overrides)
    return record_change_entry(**kwargs).entry_id


def _states(result: dict[str, object]) -> dict[str, dict[str, object]]:
    return {item["path"]: item for item in result["drift"]}  # type: ignore[union-attr]


def test_list_changes_order_and_limit(tmp_path: Path) -> None:
    root = _project(tmp_path)
    ids = [_record(root, summary=f"Change {n}") for n in range(3)]

    result = list_change_entries(str(root), limit=2)
    assert [e["entry_id"] for e in result["entries"]] == [ids[2], ids[1]]
    assert result["entries"][0]["title"] == "Change 2"
    assert result["entries"][0]["malformed"] is False
    assert result["total"] == 3
    assert result["warnings"] == []

    assert len(list_change_entries(str(root), limit=50)["entries"]) == 3
    assert len(list_change_entries(str(root), limit=1)["entries"]) == 1
    for bad in (0, 51, -1, True, 2.5, "5"):
        with pytest.raises(CodeStoryValidationError):
            list_change_entries(str(root), limit=bad)  # type: ignore[arg-type]

    response = server.list_changes(str(root), limit=51)
    assert response["ok"] is False and response["error"] == "VALIDATION_ERROR"


def test_missing_and_empty_log(tmp_path: Path) -> None:
    root = _project(tmp_path)
    assert list_change_entries(str(root)) == {"entries": [], "total": 0, "warnings": []}
    with pytest.raises(CodeStoryValidationError, match="No entry found"):
        get_change_entry(str(root), "CS-20260101-ABCDEF012345")

    (root / LOG_FILENAME).write_text("", encoding="utf-8")
    assert list_change_entries(str(root))["entries"] == []

    (root / LOG_FILENAME).write_text("# Notes\n\nNothing logged yet.\n", encoding="utf-8")
    assert list_change_entries(str(root))["entries"] == []

    with pytest.raises(CodeStoryValidationError, match="must look like"):
        get_change_entry(str(root), "not-an-id")


def test_case_insensitive_entry_ids(tmp_path: Path) -> None:
    root = _project(tmp_path)
    entry_id = _record(root)

    assert get_change_entry(str(root), entry_id.lower())["entry_id"] == entry_id
    assert get_change_entry(str(root), f"  {entry_id}  ")["entry_id"] == entry_id

    # A hand edit that lowercases the ID in the file still resolves.
    log_path = root / LOG_FILENAME
    text = log_path.read_text(encoding="utf-8")
    lowered = "cs" + entry_id[2:].lower()
    log_path.write_text(text.replace(entry_id, lowered), encoding="utf-8")
    assert list_change_entries(str(root))["entries"][0]["entry_id"] == entry_id
    assert get_change_entry(str(root), entry_id)["entry_id"] == entry_id
    assert get_change_entry(str(root), lowered)["entry_id"] == entry_id


def test_drift_unchanged_and_excerpt_intact_with_shifted_lines(tmp_path: Path) -> None:
    root = _project(tmp_path)
    entry_id = _record(root)

    result = get_change_entry(str(root), entry_id)
    item = _states(result)["src/checkout.py"]
    assert item["state"] == UNCHANGED
    assert item["recorded_span"] == [3, 4] and item["current_span"] == [3, 4]
    assert result["drift_note"] == DRIFT_NOTE
    assert result["warnings"] == []
    assert result["malformed"] is False
    assert result["entry"].startswith(f"## {entry_id} | Reserve then charge\n")

    checkout = root / "src" / "checkout.py"
    checkout.write_text("# unrelated comment\n\n" + CHECKOUT, encoding="utf-8")
    result = get_change_entry(str(root), entry_id)
    item = _states(result)["src/checkout.py"]
    assert item["state"] == FILE_MODIFIED_EXCERPT_INTACT
    assert item["recorded_span"] == [3, 4]
    assert item["current_span"] == [5, 6]
    assert any("still present at lines 5–6" in w for w in result["warnings"])

    # The MCP tool returns the same structure.
    response = server.get_change(str(root), entry_id.lower())
    assert response["ok"] is True
    assert response["drift"][0]["state"] == FILE_MODIFIED_EXCERPT_INTACT
    assert response["drift_note"] == DRIFT_NOTE


def test_drift_removed_secondary_and_missing(tmp_path: Path) -> None:
    root = _project(tmp_path)
    entry_id = _record(root, files=["src/checkout.py", "src/promo.py", "src/stock.py"])

    states = _states(get_change_entry(str(root), entry_id))
    assert {p: s["state"] for p, s in states.items()} == {
        "src/checkout.py": UNCHANGED,
        "src/promo.py": UNCHANGED,
        "src/stock.py": UNCHANGED,
    }
    assert states["src/promo.py"]["recorded_span"] is None

    (root / "src" / "checkout.py").write_text(
        CHECKOUT.replace("    charge(user, total)\n", "    try:\n        charge(user, total)\n"
                         "    except PaymentError:\n        release_stock(cart.items)\n        raise\n"),
        encoding="utf-8",
    )
    (root / "src" / "promo.py").write_text("def apply_promo(c, code):\n    return 2\n", encoding="utf-8")
    (root / "src" / "stock.py").unlink()

    result = get_change_entry(str(root), entry_id)
    states = _states(result)
    assert states["src/checkout.py"]["state"] == EXCERPT_MODIFIED_OR_REMOVED
    assert states["src/checkout.py"]["current_span"] is None
    assert states["src/promo.py"]["state"] == FILE_MODIFIED_NO_EXCERPT
    assert states["src/stock.py"]["state"] == FILE_MISSING
    assert len(result["warnings"]) == 3


def test_fence_aware_parser_ignores_headers_inside_code(tmp_path: Path) -> None:
    root = _project(tmp_path)
    fake_header = "## CS-20200101-AAAAAAAAAAAA | Not a real entry"
    (root / "notes.md").write_text(f"Example log:\n\n{fake_header}\n\nbody\n", encoding="utf-8")
    real = _record(
        root,
        summary="Document log format",
        files=["notes.md"],
        code_excerpt=f"{fake_header}\n\nbody",
        code_language="markdown",
    )
    after = _record(root, summary="Second real entry")

    result = list_change_entries(str(root))
    assert [e["entry_id"] for e in result["entries"]] == [after, real]
    assert result["warnings"] == []
    with pytest.raises(CodeStoryValidationError):
        get_change_entry(str(root), "CS-20200101-AAAAAAAAAAAA")

    entry = get_change_entry(str(root), real)
    assert _states(entry)["notes.md"]["state"] == UNCHANGED
    assert fake_header in entry["entry"]


def test_recovery_from_corrupted_middle_entry(tmp_path: Path) -> None:
    root = _project(tmp_path)
    first = _record(root, summary="First")
    middle = _record(root, summary="Middle")
    last = _record(root, summary="Last")

    # Hand edit: delete the middle entry's closing fence and Review prompt.
    log_path = root / LOG_FILENAME
    text = log_path.read_text(encoding="utf-8")
    start = text.index(f"## {middle}")
    end = text.index(f"## {last}")
    chunk = text[start:end]
    damaged = chunk[: chunk.index("```\n\n### Checks")] + "half-deleted line\n\n"
    log_path.write_text(text[:start] + damaged + text[end:], encoding="utf-8")

    result = list_change_entries(str(root))
    assert [e["entry_id"] for e in result["entries"]] == [last, middle, first]
    assert [e["malformed"] for e in result["entries"]] == [False, True, False]
    assert len(result["warnings"]) == 1
    assert middle in result["warnings"][0] and "unclosed code fence" in result["warnings"][0]

    last_entry = get_change_entry(str(root), last)
    assert last_entry["malformed"] is False
    assert last_entry["warnings"] == []
    assert _states(last_entry)["src/checkout.py"]["state"] == UNCHANGED

    middle_entry = get_change_entry(str(root), middle)
    assert middle_entry["malformed"] is True
    assert any("unclosed code fence" in w for w in middle_entry["warnings"])
    assert f"## {last}" not in middle_entry["entry"]

    # A damaged header line folds into the previous entry and is flagged there.
    text = log_path.read_text(encoding="utf-8")
    log_path.write_text(
        text.replace(f"## {middle}", "## CS-2026-BROKEN | typo\n\nstray text\n\n" + f"## {middle}"),
        encoding="utf-8",
    )
    result = list_change_entries(str(root))
    assert [e["entry_id"] for e in result["entries"]] == [last, middle, first]
    assert [e["malformed"] for e in result["entries"]] == [False, True, True]
    assert any(first in w and "damaged entry header" in w for w in result["warnings"])


def test_recovery_from_truncated_trailing_entry(tmp_path: Path) -> None:
    root = _project(tmp_path)
    first = _record(root, summary="First")
    second = _record(root, summary="Second")

    log_path = root / LOG_FILENAME
    text = log_path.read_text(encoding="utf-8")
    cut = text.index("reserve_stock(cart.items)", text.index(f"## {second}"))
    log_path.write_text(text[:cut], encoding="utf-8")

    result = list_change_entries(str(root))
    assert [e["entry_id"] for e in result["entries"]] == [second, first]
    assert result["entries"][0]["malformed"] is True
    assert any(second in w and "unclosed code fence" in w for w in result["warnings"])

    assert get_change_entry(str(root), first)["warnings"] == []

    truncated = get_change_entry(str(root), second)
    assert truncated["malformed"] is True
    # Fingerprints come before the code block, so whole-file drift still works.
    assert _states(truncated)["src/checkout.py"]["state"] == UNCHANGED
    (root / "src" / "checkout.py").write_text("# edited\n" + CHECKOUT, encoding="utf-8")
    truncated = get_change_entry(str(root), second)
    assert _states(truncated)["src/checkout.py"]["state"] == FILE_MODIFIED_NO_EXCERPT
    assert any("excerpt-level drift is unavailable" in w for w in truncated["warnings"])

    # Recording after a truncated tail starts a clean, parseable entry.
    third = _record(root, summary="Third")
    parsed = parse_log(log_path.read_text(encoding="utf-8"))
    assert [e.entry_id for e in parsed.entries] == [first, second, third]
    assert get_change_entry(str(root), third)["malformed"] is False
