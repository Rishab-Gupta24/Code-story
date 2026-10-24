"""Phase 1 test suite for validated local logging (see tasks.md)."""

from __future__ import annotations

import functools
import hashlib
import re
from pathlib import Path

import pytest
from filelock import FileLock

from code_story import server
from code_story.log import (
    LOCK_FILENAME,
    LOG_FILENAME,
    CodeStoryValidationError,
    LockTimeoutError,
    record_change_entry,
)

ENTRY_ID_RE = re.compile(r"^CS-\d{8}-[0-9A-F]{12}$")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _valid_kwargs(root: Path, **overrides: object) -> dict[str, object]:
    kwargs: dict[str, object] = dict(
        project_root=str(root),
        summary="Initial valid entry",
        explanation="Sets x and y.",
        reason="Baseline setup.",
        files=["app.py"],
        code_excerpt="x = 1\ny = 2",
        checks="Ran unit check.",
        review_question="Are x and y used?",
        code_language="python",
    )
    kwargs.update(overrides)
    return kwargs


def _seeded_root(tmp_path: Path) -> tuple[Path, Path, str]:
    """Project with app.py and one valid entry; returns (root, log_path, log_text)."""
    root = tmp_path / "proj"
    root.mkdir()
    (root / "app.py").write_text("x = 1\ny = 2\n", encoding="utf-8")
    record_change_entry(**_valid_kwargs(root))
    log_path = root / LOG_FILENAME
    return root, log_path, log_path.read_text(encoding="utf-8")


def test_record_two_valid_entries(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    (root / "src" / "cart").mkdir(parents=True)
    checkout = root / "src" / "cart" / "checkout.py"
    checkout.write_text(
        "def checkout(cart, user):\n"
        "    # apply discounts first\n"
        "    total = apply_promo(cart, user.promo_code)\n"
        "    reserve_stock(cart.items)\n"
        "    charge(user, total)\n",
        encoding="utf-8",
    )
    helper = root / "src" / "cart" / "promo.py"
    helper.write_text("def apply_promo(cart, code):\n    return cart.total\n", encoding="utf-8")

    first = record_change_entry(
        project_root=str(root),
        summary="Apply promo before reserving stock",
        explanation="Applies the promo code, reserves items, and charges the card.",
        reason="Bundled items were not discounted.",
        files=["src/cart/checkout.py", "src/cart/promo.py"],
        code_excerpt="    total = apply_promo(cart, user.promo_code)\n"
        "    reserve_stock(cart.items)\n"
        "    charge(user, total)",
        checks="Unit tests for apply_promo passed.",
        review_question="If charge() raises, is the reserved stock released?",
        code_language="python",
    )
    second = record_change_entry(
        project_root=str(root),
        summary="Return cart total from promo helper",
        explanation="The helper currently returns the undiscounted total.",
        reason="Placeholder until promo rules land.",
        files=["src/cart/promo.py"],
        code_excerpt="    return cart.total",
        checks="None run.",
        review_question="Should an unknown promo code raise?",
    )

    assert ENTRY_ID_RE.match(first.entry_id)
    assert ENTRY_ID_RE.match(second.entry_id)
    assert first.entry_id != second.entry_id
    assert first.warnings == [] and second.warnings == []

    log_path = root / LOG_FILENAME
    assert Path(first.log_path) == log_path.resolve()
    text = log_path.read_text(encoding="utf-8")

    assert text.startswith(f"## {first.entry_id} | Apply promo before reserving stock\n")
    assert f"\n\n## {second.entry_id} | Return cart total from promo helper\n" in text
    recorded = re.findall(r"^\*\*Recorded:\*\* (.+)  $", text, re.MULTILINE)
    assert len(recorded) == 2
    for stamp in recorded:
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2} [+-]\d{4}", stamp)
    assert "**Files:** `src/cart/checkout.py`, `src/cart/promo.py`\n" in text

    excerpt = (
        "    total = apply_promo(cart, user.promo_code)\n"
        "    reserve_stock(cart.items)\n"
        "    charge(user, total)"
    )
    assert (
        f"- `src/cart/checkout.py`: `{_sha(checkout.read_bytes())}` "
        f"(lines 3–5, excerpt SHA-256: `{_sha(excerpt.encode())}`)\n"
    ) in text
    assert f"- `src/cart/promo.py`: `{_sha(helper.read_bytes())}` (no excerpt tracked)\n" in text
    assert (
        f"- `src/cart/promo.py`: `{_sha(helper.read_bytes())}` "
        f"(lines 2–2, excerpt SHA-256: `{_sha(b'    return cart.total')}`)\n"
    ) in text
    assert f"```python\n{excerpt}\n```\n" in text
    assert "> If charge() raises, is the reserved stock released?\n" in text


def test_reject_relative_root_and_path_traversal(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    src_file = root / "app.py"
    src_file.write_text("x = 1\ny = 2\n", encoding="utf-8")

    outside_file = tmp_path / "outside.py"
    outside_file.write_text("x = 1\ny = 2\n", encoding="utf-8")

    # Seed one valid entry first
    record_change_entry(
        project_root=str(root),
        summary="Initial valid entry",
        explanation="Sets x and y.",
        reason="Baseline setup.",
        files=["app.py"],
        code_excerpt="x = 1\ny = 2",
        checks="Ran unit check.",
        review_question="Are x and y used?",
        code_language="python",
    )
    log_path = root / ".ai-code-log.md"
    before = log_path.read_text(encoding="utf-8")

    # 1. Reject relative project_root
    with pytest.raises((CodeStoryValidationError, ValueError)):
        record_change_entry(
            project_root="relative/path",
            summary="Relative root",
            explanation="Should fail.",
            reason="Test.",
            files=["app.py"],
            code_excerpt="x = 1",
            checks="None.",
            review_question="Fail?",
        )

    # 2. Reject ../ path traversal
    with pytest.raises((CodeStoryValidationError, ValueError)):
        record_change_entry(
            project_root=str(root),
            summary="Dot-dot traversal",
            explanation="Should fail.",
            reason="Test.",
            files=["../outside.py"],
            code_excerpt="x = 1\ny = 2",
            checks="None.",
            review_question="Fail?",
        )

    # 3. Reject an absolute file path, even one pointing outside the root
    with pytest.raises((CodeStoryValidationError, ValueError)):
        record_change_entry(**_valid_kwargs(root, files=[str(outside_file)]))

    assert log_path.read_text(encoding="utf-8") == before


def test_reject_symlink_escape(tmp_path: Path) -> None:
    root, log_path, before = _seeded_root(tmp_path)
    outside_file = tmp_path / "outside_secret.py"
    outside_file.write_text("secret_logic = 42\n", encoding="utf-8")

    symlink_path = root / "linked_secret.py"
    try:
        symlink_path.symlink_to(outside_file)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(
            f"OS refused to create symlink without Developer Mode or elevated privileges: {exc}"
        )

    with pytest.raises((CodeStoryValidationError, ValueError)):
        record_change_entry(
            project_root=str(root),
            summary="Symlink escape attempt",
            explanation="Attempts to log a symlink pointing outside project_root.",
            reason="Security test.",
            files=["linked_secret.py"],
            code_excerpt="secret_logic = 42",
            checks="None.",
            review_question="Did symlink escape get rejected?",
        )

    assert log_path.read_text(encoding="utf-8") == before


def test_reject_missing_or_blank_fields(tmp_path: Path) -> None:
    root, log_path, before = _seeded_root(tmp_path)

    for field_name in (
        "summary",
        "explanation",
        "reason",
        "code_excerpt",
        "checks",
        "review_question",
    ):
        for blank in ("", "   ", "\n\t\n"):
            with pytest.raises(CodeStoryValidationError):
                record_change_entry(**_valid_kwargs(root, **{field_name: blank}))

    with pytest.raises(CodeStoryValidationError):
        record_change_entry(**_valid_kwargs(root, files=[]))
    with pytest.raises(CodeStoryValidationError):
        record_change_entry(**_valid_kwargs(root, files=["  "]))
    with pytest.raises(CodeStoryValidationError):
        record_change_entry(**_valid_kwargs(root, files=["missing.py"]))
    with pytest.raises(CodeStoryValidationError):
        record_change_entry(**_valid_kwargs(root, project_root=""))

    assert log_path.read_text(encoding="utf-8") == before

    # Newlines in summary are collapsed so the header stays on one line.
    result = record_change_entry(**_valid_kwargs(root, summary="Line one\nline two"))
    assert f"## {result.entry_id} | Line one line two\n" in log_path.read_text(encoding="utf-8")


def test_reject_fabricated_excerpt(tmp_path: Path) -> None:
    root, log_path, before = _seeded_root(tmp_path)

    with pytest.raises(CodeStoryValidationError):
        record_change_entry(**_valid_kwargs(root, code_excerpt="x = 1\nz = 3"))
    assert log_path.read_text(encoding="utf-8") == before

    # CRLF source file matches an LF excerpt, and vice versa.
    (root / "crlf.py").write_bytes(b"a = 1\r\nb = 2\r\n")
    (root / "lf.py").write_bytes(b"c = 3\nd = 4\n")
    crlf = record_change_entry(
        **_valid_kwargs(root, files=["crlf.py"], code_excerpt="a = 1\nb = 2")
    )
    lf = record_change_entry(
        **_valid_kwargs(root, files=["lf.py"], code_excerpt="\r\nc = 3\r\nd = 4\r\n")
    )
    text = log_path.read_text(encoding="utf-8")
    assert crlf.entry_id in text and lf.entry_id in text
    assert "```python\nc = 3\nd = 4\n```" in text

    # Duplicate blocks: the first occurrence's span is recorded.
    (root / "dup.py").write_text(
        "def f():\n    return 1\n\n\ndef f():\n    return 1\n", encoding="utf-8"
    )
    record_change_entry(
        **_valid_kwargs(root, files=["dup.py"], code_excerpt="def f():\n    return 1")
    )
    text = log_path.read_text(encoding="utf-8")
    assert re.search(r"- `dup\.py`: `[0-9a-f]{64}` \(lines 1–2, excerpt SHA-256", text)


def test_excerpt_caps_and_secret_scanning(tmp_path: Path) -> None:
    root, log_path, _ = _seeded_root(tmp_path)

    lines = [f"v{i} = {i}" for i in range(101)]
    (root / "big.py").write_text("\n".join(lines) + "\n", encoding="utf-8")
    hundred = "\n".join(lines[:100])
    # Blank lines around the excerpt are trimmed before the cap is applied.
    record_change_entry(
        **_valid_kwargs(root, files=["big.py"], code_excerpt=f"\n\n{hundred}\n\n\n")
    )
    with pytest.raises(CodeStoryValidationError, match="101 lines"):
        record_change_entry(
            **_valid_kwargs(root, files=["big.py"], code_excerpt="\n".join(lines))
        )

    long_line = "s = '" + "a" * 3994 + "'"
    assert len(long_line) == 4000
    (root / "wide.py").write_text(long_line + "a\n", encoding="utf-8")
    record_change_entry(
        **_valid_kwargs(root, files=["wide.py"], code_excerpt=f"\n{long_line}\n")
    )
    with pytest.raises(CodeStoryValidationError, match="4001 characters"):
        record_change_entry(
            **_valid_kwargs(root, files=["wide.py"], code_excerpt=long_line + "a")
        )

    # Tokens are assembled at runtime so this file holds no literal token strings.
    tokens = [
        "sk" + "-" + "A1b2C3d4E5f6G7h8I9j0",
        "AK" + "IA" + "ABCDEFGHIJKLMNOP",
        "AS" + "IA" + "QRSTUVWXYZ234567",
        "gh" + "p_" + "a" * 24,
        "xo" + "xb-" + "1234567890-abcdef",
        "-----BEGIN " + "RSA PRIVATE KEY-----",
    ]
    before = log_path.read_text(encoding="utf-8")
    for token in tokens:
        with pytest.raises(CodeStoryValidationError, match="cannot catch every secret"):
            record_change_entry(
                **_valid_kwargs(root, explanation=f"Uses credential {token} for auth.")
            )
    (root / "leak.py").write_text(f'TOKEN = "{tokens[0]}"\n', encoding="utf-8")
    with pytest.raises(CodeStoryValidationError):
        record_change_entry(
            **_valid_kwargs(root, files=["leak.py"], code_excerpt=f'TOKEN = "{tokens[0]}"')
        )
    assert log_path.read_text(encoding="utf-8") == before

    # Generic assignments warn but still record.
    (root / "fixture.py").write_text('password = "hunter2"\n', encoding="utf-8")
    result = record_change_entry(
        **_valid_kwargs(root, files=["fixture.py"], code_excerpt='password = "hunter2"')
    )
    assert len(result.warnings) == 1
    assert "password" in result.warnings[0]
    assert result.entry_id in log_path.read_text(encoding="utf-8")


def test_dynamic_backtick_fence_and_hand_edited_tail(tmp_path: Path) -> None:
    root, log_path, _ = _seeded_root(tmp_path)

    (root / "docs.py").write_text(
        'DOC = """\n```python\nprint(1)\n```\n"""\n', encoding="utf-8"
    )
    excerpt = 'DOC = """\n```python\nprint(1)\n```\n"""'
    record_change_entry(**_valid_kwargs(root, files=["docs.py"], code_excerpt=excerpt))
    text = log_path.read_text(encoding="utf-8")
    assert f"\n````python\n{excerpt}\n````\n" in text

    (root / "five.py").write_text("FENCE = '````'\n", encoding="utf-8")
    record_change_entry(
        **_valid_kwargs(root, files=["five.py"], code_excerpt="FENCE = '````'", code_language="")
    )
    text = log_path.read_text(encoding="utf-8")
    assert "\n`````\nFENCE = '````'\n`````\n" in text

    # A hand edit without a trailing newline still gets a clean entry boundary.
    with open(log_path, "a", encoding="utf-8", newline="\n") as handle:
        handle.write("Manual note from a reviewer")
    result = record_change_entry(**_valid_kwargs(root, summary="After hand edit"))
    text = log_path.read_text(encoding="utf-8")
    assert f"Manual note from a reviewer\n\n## {result.entry_id} | After hand edit\n" in text


def test_lock_timeout_no_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, log_path, before = _seeded_root(tmp_path)

    with FileLock(str(root / LOCK_FILENAME)):
        with pytest.raises(LockTimeoutError) as excinfo:
            record_change_entry(**_valid_kwargs(root), lock_timeout=0.3)
        assert excinfo.value.code == "LOCK_TIMEOUT"

    assert log_path.read_text(encoding="utf-8") == before

    # The MCP tool surfaces the same condition as a structured LOCK_TIMEOUT error.
    monkeypatch.setattr(
        server, "record_change_entry", functools.partial(record_change_entry, lock_timeout=0.3)
    )
    with FileLock(str(root / LOCK_FILENAME)):
        response = server.record_change(**_valid_kwargs(root))
    assert response["ok"] is False
    assert response["error"] == "LOCK_TIMEOUT"
    assert log_path.read_text(encoding="utf-8") == before
