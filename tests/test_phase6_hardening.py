"""Phase 6 hardening: concurrent appends, scale timings, and fuzzing.

Fuzz tests use the standard library's ``random`` with fixed seeds, so every
failure reproduces exactly. Timings measure the library functions behind the
MCP tools (no stdio round trip). Set ``CODE_STORY_TIMINGS_OUT`` to a file path
to save the measured timings as JSON.
"""

from __future__ import annotations

import json
import os
import platform
import random
import statistics
import subprocess
import sys
import time
from pathlib import Path

import pytest

from code_story.log import (
    LOG_FILENAME,
    CodeStoryValidationError,
    normalize_excerpt,
    record_change_entry,
)
from code_story.review import UNCHANGED, get_change_entry, list_change_entries, parse_log


def _record(root: Path, rel: str, excerpt: str, summary: str = "Change") -> str:
    return record_change_entry(
        project_root=str(root),
        summary=summary,
        explanation="Explains the change.",
        reason="Needed for the test.",
        files=[rel],
        code_excerpt=excerpt,
        checks="None run.",
        review_question="Is this right?",
        code_language="python",
    ).entry_id


# ------------------------------------------------------------------ concurrency

_WORKER = r"""
import sys, time
from pathlib import Path
from code_story.log import record_change_entry

root, worker, go = sys.argv[1], int(sys.argv[2]), Path(sys.argv[3])
while not go.exists():
    time.sleep(0.005)
for k in range(5):
    record_change_entry(
        project_root=root,
        summary=f"worker {worker} entry {k}",
        explanation=f"Entry {k} from worker {worker}.\n" + "x" * 2000,
        reason="Concurrency test.",
        files=["src/mod.py"],
        code_excerpt=f"def f{worker}():\n    return {worker}",
        checks="None run.",
        review_question=f"Did worker {worker} entry {k} survive intact?",
        code_language="python",
    )
"""


def test_concurrent_appends_8_workers_x_5(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "mod.py").write_text(
        "".join(f"def f{w}():\n    return {w}\n\n" for w in range(8)), encoding="utf-8"
    )
    go = tmp_path / "go"
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", _WORKER, str(tmp_path), str(w), str(go)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for w in range(8)
    ]
    go.write_text("go")  # release all workers at once
    for p in procs:
        out, err = p.communicate(timeout=120)
        assert p.returncode == 0, err

    text = (tmp_path / LOG_FILENAME).read_text(encoding="utf-8")
    parsed = parse_log(text)
    assert parsed.warnings == []
    assert len(parsed.entries) == 40
    assert len({e.entry_id for e in parsed.entries}) == 40
    assert all(not e.problems for e in parsed.entries)

    titles = [e.title for e in parsed.entries]
    assert sorted(titles) == sorted(f"worker {w} entry {k}" for w in range(8) for k in range(5))
    for w in range(8):
        # Each worker's own entries land in the order it wrote them.
        mine = [t for t in titles if t.startswith(f"worker {w} ")]
        assert mine == [f"worker {w} entry {k}" for k in range(5)]
    for e in parsed.entries:
        # No interleaving: each entry's body belongs to the worker in its title.
        w, k = e.title.split()[1], e.title.split()[3]
        assert e.excerpt == f"def f{w}():\n    return {w}"
        assert f"Entry {k} from worker {w}.\n" + "x" * 2000 in e.text
        assert e.text.rstrip().endswith(f"> Did worker {w} entry {k} survive intact?")


# ------------------------------------------------------------------ scale timings

_REPS = 30


def _stats(samples: list[float]) -> dict[str, float]:
    ordered = sorted(samples)
    p95 = ordered[min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))]
    return {"median_ms": round(statistics.median(ordered) * 1000, 2), "p95_ms": round(p95 * 1000, 2)}


def _timed(fn) -> float:
    start = time.perf_counter()
    fn()
    return time.perf_counter() - start


@pytest.mark.parametrize("size", [100, 250])
def test_scale_timings(tmp_path: Path, size: int) -> None:
    (tmp_path / "src").mkdir()
    source = tmp_path / "src" / "mod.py"
    source.write_text(
        "".join(f"def f{i}(x):\n    return x + {i}\n\n" for i in range(size + _REPS)),
        encoding="utf-8",
    )
    ids = [_record(tmp_path, "src/mod.py", f"def f{i}(x):\n    return x + {i}", f"Entry {i}") for i in range(size)]

    # record_change: append at the stated size (the log grows by _REPS entries).
    record = [
        _timed(lambda i=i: _record(tmp_path, "src/mod.py", f"def f{i}(x):\n    return x + {i}"))
        for i in range(size, size + _REPS)
    ]
    listing = [_timed(lambda: list_change_entries(str(tmp_path), 50)) for _ in range(_REPS)]
    middle = ids[size // 2]
    getting = [_timed(lambda: get_change_entry(str(tmp_path), middle)) for _ in range(_REPS)]

    # Correctness at scale.
    result = list_change_entries(str(tmp_path), 50)
    assert result["total"] == size + _REPS and result["warnings"] == []
    change = get_change_entry(str(tmp_path), middle)
    assert change["title"] == f"Entry {size // 2}"
    assert [d["state"] for d in change["drift"]] == [UNCHANGED]

    timings = {
        "log_entries": size,
        "log_bytes": (tmp_path / LOG_FILENAME).stat().st_size,
        "record_change": _stats(record),
        "list_changes": _stats(listing),
        "get_change": _stats(getting),
        "reps": _REPS,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "processor": platform.processor(),
        "cpu_count": os.cpu_count(),
    }
    print(json.dumps(timings))
    out = os.environ.get("CODE_STORY_TIMINGS_OUT")
    if out:
        with open(out, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(timings) + "\n")

    # A loose ceiling that only catches pathological slowdowns, not machine variance.
    for op in ("record_change", "list_changes", "get_change"):
        assert timings[op]["p95_ms"] < 2000, (op, timings[op])


# ------------------------------------------------------------------ fuzzing

_TRICKY_LINES = [
    "## CS-20261025-ABCDEF123456 | Fake header",
    "## cs-20261025-abcdef123456 | lowercase header",
    "## CS-2026 | damaged header",
    "**Recorded:** 2026-10-25 10:00 +0400  ",
    "**Files:** `src/x.py`",
    "- `src/x.py`: `" + "a" * 64 + "` (no excerpt tracked)",
    "### Code",
    "### Review prompt",
    "```",
    "````",
    "```python",
    "~~~",
    "~~~~~",
    "   ```",
    "    ```",
    "``` `not a fence`",
    "> quoted",
    "",
    "   ",
]
_ALPHABET = (
    "abcXYZ019 _-|#*>`~()[]{}\t"
    "éßΩЖ中文日本語한국어"
    "\u00a0\u200b\u2028\u2029\ufeff"
    "🙂👩‍💻🏳️‍🌈"
)


def _random_text(rng: random.Random, max_len: int = 40) -> str:
    return "".join(rng.choice(_ALPHABET) for _ in range(rng.randint(0, max_len)))


def _random_document(rng: random.Random) -> str:
    lines = []
    for _ in range(rng.randint(0, 60)):
        lines.append(rng.choice(_TRICKY_LINES) if rng.random() < 0.6 else _random_text(rng))
    return rng.choice(["\n", "\r\n"]).join(lines)


def test_fuzz_parser_never_raises_on_arbitrary_text() -> None:
    rng = random.Random(6001)
    for _ in range(2000):
        doc = _random_document(rng)
        parsed = parse_log(doc)
        lines = [e.line for e in parsed.entries]
        assert lines == sorted(lines) and len(set(lines)) == len(lines)
        for e in parsed.entries:
            assert e.entry_id == e.entry_id.upper()
            assert e.text.endswith("\n")


def _random_excerpt(rng: random.Random) -> str:
    """Excerpt lines mixing Unicode with nested backtick and tilde runs."""
    lines = []
    for _ in range(rng.randint(1, 8)):
        kind = rng.random()
        if kind < 0.3:
            lines.append(" " * rng.randint(0, 6) + rng.choice("`~") * rng.randint(1, 9) + _random_text(rng, 10))
        elif kind < 0.4:
            lines.append(rng.choice(_TRICKY_LINES[6:16]))
        elif kind < 0.5:
            lines.append("x = " + _random_text(rng, 8) + "\r" + _random_text(rng, 8))  # lone CR
        else:
            lines.append("x = " + repr(_random_text(rng)))
    return "\n".join(lines)


def test_fuzz_round_trip_unicode_and_nested_fences(tmp_path: Path) -> None:
    rng = random.Random(6002)
    expected = []
    for i in range(80):
        rel = f"src/m{i}.py"
        excerpt = _random_excerpt(rng)
        path = tmp_path / rel
        path.parent.mkdir(exist_ok=True)
        path.write_text(f"# file {i}\n{excerpt}\n# end\n", encoding="utf-8", newline="\n")
        summary = f"{i} " + _random_text(rng, 20)
        entry_id = _record(tmp_path, rel, excerpt, summary)
        expected.append((entry_id, " ".join(summary.split()), normalize_excerpt(excerpt)))

    parsed = parse_log((tmp_path / LOG_FILENAME).read_bytes().decode("utf-8"))
    assert parsed.warnings == []
    assert [(e.entry_id, e.title, e.excerpt) for e in parsed.entries] == expected
    for entry_id, _, _ in expected[::5]:
        change = get_change_entry(str(tmp_path), entry_id)
        assert change["warnings"] == [] and change["drift"][0]["state"] == UNCHANGED


def test_fuzz_truncated_trailing_entries(tmp_path: Path) -> None:
    rng = random.Random(6003)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "mod.py").write_text(
        "".join(f"def f{i}():\n    return '``` {i}'\n\n" for i in range(12)), encoding="utf-8"
    )
    for i in range(12):
        _record(tmp_path, "src/mod.py", f"def f{i}():\n    return '``` {i}'", f"Entry {i}")
    full = (tmp_path / LOG_FILENAME).read_text(encoding="utf-8")
    complete = parse_log(full).entries
    starts = [full.index(f"## {e.entry_id} ") for e in complete]

    for _ in range(400):
        cut = rng.randint(0, len(full))
        parsed = parse_log(full[:cut])
        # Every entry that ends before the cut parses exactly as in the full log.
        intact = [e for e, s in zip(complete, starts[1:] + [len(full)]) if s <= cut]
        got = parsed.entries[: len(intact)]
        assert [(e.entry_id, e.excerpt) for e in got] == [(e.entry_id, e.excerpt) for e in intact]
        assert all(not e.problems for e in got[:-1])
        if got:
            # A cut inside the next entry's header leaves a damaged header line, which
            # (as specified in Phase 2) folds into the previous entry and is flagged there.
            assert all(p.startswith("contains a damaged entry header") for p in got[-1].problems)
        # At most one trailing entry may be cut short, and it is never silently merged.
        assert len(parsed.entries) - len(intact) <= 1


_GARBAGE = [
    None, 0, 1.5, True, [], {}, "", " ", "\n", "\x00", "a\x00b", "..", "../x",
    "/etc/passwd", "C:\\Windows", "\\\\server\\share", "src/" + "a" * 300, "🙂", "\ud800",
    ["src/ok.py"], ["src/ok.py", None], ["../outside.py"], ["src\x00ok.py"], ["src/missing.py"],
    ["/abs.py"], [""], ["src/ok.py"] * 3,
]


def test_fuzz_validator_only_raises_validation_errors(tmp_path: Path) -> None:
    rng = random.Random(6004)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "ok.py").write_text("def ok():\n    return 1\n", encoding="utf-8")
    valid = {
        "project_root": str(tmp_path),
        "summary": "Valid summary",
        "explanation": "Explains.",
        "reason": "Because.",
        "files": ["src/ok.py"],
        "code_excerpt": "def ok():\n    return 1",
        "checks": "None run.",
        "review_question": "Right?",
        "code_language": "python",
    }
    successes = 0
    for _ in range(600):
        args = dict(valid)
        for name in rng.sample(sorted(valid), rng.randint(1, 3)):
            args[name] = rng.choice(_GARBAGE + [_random_text(rng)])
        try:
            record_change_entry(**args)
            successes += 1
        except CodeStoryValidationError:
            pass
    # Whatever got through must have left a log that still parses cleanly.
    if successes:
        parsed = parse_log((tmp_path / LOG_FILENAME).read_text(encoding="utf-8"))
        assert len(parsed.entries) == successes and parsed.warnings == []


# ------------------------------------------------------------------ fuzz findings


def test_lone_surrogates_are_validation_errors(tmp_path: Path) -> None:
    """Found by fuzzing: a lone surrogate used to crash the write with UnicodeEncodeError."""
    (tmp_path / "ok.py").write_text("x = 1\n", encoding="utf-8")
    args = dict(
        project_root=str(tmp_path), summary="s", explanation="e", reason="r",
        files=["ok.py"], code_excerpt="x = 1", checks="c", review_question="q",
    )
    for name, bad in [("explanation", "bad \ud800 text"), ("files", ["ok\udfff.py"])]:
        with pytest.raises(CodeStoryValidationError, match="UTF-8"):
            record_change_entry(**{**args, name: bad})
    assert not (tmp_path / LOG_FILENAME).exists()


def test_lone_carriage_returns_round_trip(tmp_path: Path) -> None:
    """Found by fuzzing: a lone CR in an excerpt was read back as LF (false hand-edit
    warning), and a trailing CR before the file's LF made the excerpt unmatchable."""
    inner = 'x = "a\rb"'
    (tmp_path / "m.py").write_bytes(f"# top\r\n{inner}\r\ny = 2\r\n".encode())
    for excerpt in (inner, inner + "\r"):
        entry_id = _record(tmp_path, "m.py", excerpt)
        change = get_change_entry(str(tmp_path), entry_id)
        assert change["warnings"] == [] and change["drift"][0]["state"] == UNCHANGED
        assert change["drift"][0]["current_span"] == [2, 2]


# ------------------------------------------------------------------ archive workflow


def test_archive_split_at_entry_header(tmp_path: Path) -> None:
    """The README's manual archive workflow: cut at an entry header, move the older part."""
    (tmp_path / "m.py").write_text("".join(f"x{i} = {i}\n" for i in range(6)), encoding="utf-8")
    ids = [_record(tmp_path, "m.py", f"x{i} = {i}", f"Entry {i}") for i in range(6)]
    log = tmp_path / LOG_FILENAME
    text = log.read_bytes().decode("utf-8")

    cut = text.index(f"## {ids[4]} ")  # keep the two newest entries
    (tmp_path / ".ai-code-log.archive.md").write_text(text[:cut], encoding="utf-8", newline="\n")
    log.write_text(text[cut:], encoding="utf-8", newline="\n")

    archive = parse_log((tmp_path / ".ai-code-log.archive.md").read_text(encoding="utf-8"))
    assert [e.entry_id for e in archive.entries] == ids[:4] and archive.warnings == []
    kept = list_change_entries(str(tmp_path), 50)
    assert [e["entry_id"] for e in kept["entries"]] == [ids[5], ids[4]] and kept["warnings"] == []
    assert get_change_entry(str(tmp_path), ids[4])["drift"][0]["state"] == UNCHANGED
    with pytest.raises(CodeStoryValidationError, match="No entry found"):
        get_change_entry(str(tmp_path), ids[0])  # archived entries aren't searched

    new_id = _record(tmp_path, "m.py", "x0 = 0", "After archiving")
    assert list_change_entries(str(tmp_path), 50)["entries"][0]["entry_id"] == new_id
    assert parse_log(log.read_bytes().decode("utf-8")).warnings == []
