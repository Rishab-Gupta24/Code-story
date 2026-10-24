"""Reading ``.ai-code-log.md`` back: fence-aware parsing, recovery, and drift.

The parser tolerates hand-edited and truncated logs: a damaged entry is kept,
flagged with problems, and never stops the entries around it from parsing.
Drift states tell the reviewer where to look, not whether a bug exists.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from code_story.log import (
    LOCK_TIMEOUT_SECONDS,
    CodeStoryValidationError,
    _read_log,
    _sha256,
    _validate_root,
    find_excerpt_span,
    normalize_excerpt,
)

DRIFT_NOTE = (
    "Drift states show where to inspect the live code; they do not say whether "
    "a bug is present."
)

UNCHANGED = "unchanged"
FILE_MODIFIED_EXCERPT_INTACT = "file_modified_excerpt_intact"
EXCERPT_MODIFIED_OR_REMOVED = "excerpt_modified_or_removed"
FILE_MODIFIED_NO_EXCERPT = "file_modified_no_excerpt"
FILE_MISSING = "file_missing"

_ENTRY_ID_RE = re.compile(r"^CS-\d{8}-[0-9A-F]{12}$", re.IGNORECASE)
_HEADER_RE = re.compile(r"^## (CS-\d{8}-[0-9A-F]{12}) \| (.+)$", re.IGNORECASE)
_DAMAGED_HEADER_RE = re.compile(r"^## CS-", re.IGNORECASE)
_FENCE_OPEN_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_RECORDED_RE = re.compile(r"^\*\*Recorded:\*\* (.+?)\s*$")
_FINGERPRINT_RE = re.compile(
    r"^- `([^`]+)`: `([0-9a-fA-F]{64})` \("
    r"(?:lines (\d+)[–-](\d+), excerpt SHA-256: `([0-9a-fA-F]{64})`|no excerpt tracked)"
    r"\)\s*$"
)


@dataclass
class Fingerprint:
    path: str
    sha256: str
    span: tuple[int, int] | None = None
    excerpt_sha256: str | None = None


@dataclass
class LogEntry:
    entry_id: str
    title: str
    line: int
    text: str
    recorded: str | None = None
    fingerprints: list[Fingerprint] = field(default_factory=list)
    excerpt: str | None = None
    problems: list[str] = field(default_factory=list)


@dataclass
class ParsedLog:
    entries: list[LogEntry]
    warnings: list[str]


def _fence_opener(line: str) -> tuple[str, int] | None:
    match = _FENCE_OPEN_RE.match(line)
    if not match:
        return None
    marker, info = match.groups()
    # CommonMark: a backtick fence's info string may not contain backticks.
    if marker[0] == "`" and "`" in info:
        return None
    return marker[0], len(marker)


def _closes(line: str, fence: tuple[str, int]) -> bool:
    char, length = fence
    stripped = line.strip()
    return (
        len(line) - len(line.lstrip(" ")) <= 3
        and len(stripped) >= length
        and set(stripped) == {char}
    )


def _starts_entry(lines: list[str], index: int) -> bool:
    """A header followed by a ``**Recorded:**`` line is a real entry start."""
    for line in lines[index + 1 : index + 4]:
        if line.strip():
            return bool(_RECORDED_RE.match(line))
    return False


def _find_headers(lines: list[str]) -> list[int]:
    headers: list[int] = []
    fence: tuple[str, int] | None = None
    for i, line in enumerate(lines):
        if fence is None:
            if _HEADER_RE.match(line):
                headers.append(i)
            else:
                fence = _fence_opener(line)
        elif _closes(line, fence):
            fence = None
        elif _HEADER_RE.match(line) and _starts_entry(lines, i):
            # An unclosed fence from a damaged entry: recover at the next real header.
            fence = None
            headers.append(i)
    return headers


def _parse_entry(lines: list[str], start: int) -> LogEntry:
    header = _HEADER_RE.match(lines[0])
    assert header is not None
    entry = LogEntry(
        entry_id=header.group(1).upper(),
        title=header.group(2).strip(),
        line=start + 1,
        text="\n".join(lines).rstrip() + "\n",
    )
    recorded: list[str] = []
    sections: set[str] = set()
    fence: tuple[str, int] | None = None
    code_lines: list[str] | None = None
    capturing = False
    for line in lines[1:]:
        if fence is not None:
            if _closes(line, fence):
                fence = None
                if capturing:
                    capturing = False
                    entry.excerpt = normalize_excerpt("\n".join(code_lines or []))
            elif capturing:
                assert code_lines is not None
                code_lines.append(line)
            continue
        opener = _fence_opener(line)
        if opener is not None:
            fence = opener
            if "### Code" in sections and code_lines is None:
                code_lines = []
                capturing = True
            continue
        if line.startswith("### "):
            sections.add(line.strip())
        elif _RECORDED_RE.match(line):
            recorded.append(_RECORDED_RE.match(line).group(1))  # type: ignore[union-attr]
        elif _DAMAGED_HEADER_RE.match(line):
            entry.problems.append(f"contains a damaged entry header: {line.strip()!r}")
        else:
            fp = _FINGERPRINT_RE.match(line)
            if fp:
                path, sha, start_line, end_line, excerpt_sha = fp.groups()
                span = (int(start_line), int(end_line)) if start_line else None
                entry.fingerprints.append(
                    Fingerprint(path, sha.lower(), span, excerpt_sha.lower() if excerpt_sha else None)
                )

    if fence is not None:
        entry.problems.append("has an unclosed code fence (truncated or hand-edited)")
    if not recorded:
        entry.problems.append("is missing its **Recorded:** line")
    elif len(recorded) > 1:
        entry.problems.append("has more than one **Recorded:** line (entries may have merged)")
    else:
        entry.recorded = recorded[0]
    if not entry.fingerprints:
        entry.problems.append("has no readable source fingerprints")
    if "### Code" not in sections:
        entry.problems.append("is missing its ### Code section")
    elif entry.excerpt is None and fence is None:
        entry.problems.append("has no code block under ### Code")
    if "### Review prompt" not in sections:
        entry.problems.append("is missing its ### Review prompt section (possibly truncated)")
    return entry


def parse_log(text: str) -> ParsedLog:
    lines = text.replace("\r\n", "\n").split("\n")
    headers = _find_headers(lines)
    entries = []
    for k, start in enumerate(headers):
        end = headers[k + 1] if k + 1 < len(headers) else len(lines)
        entries.append(_parse_entry(lines[start:end], start))

    warnings = [
        f"Entry {e.entry_id} (line {e.line}) is malformed: it {'; it '.join(e.problems)}. "
        "Other entries were parsed normally."
        for e in entries
        if e.problems
    ]
    seen: dict[str, int] = {}
    for e in entries:
        if e.entry_id in seen:
            warnings.append(
                f"Entry ID {e.entry_id} appears more than once (lines {seen[e.entry_id]} "
                f"and {e.line}); lookups return the first."
            )
        else:
            seen[e.entry_id] = e.line
    return ParsedLog(entries=entries, warnings=warnings)


def _span(span: tuple[int, int] | None) -> list[int] | None:
    return list(span) if span else None


def file_drift(root: Path, entry: LogEntry) -> tuple[list[dict[str, object]], list[str]]:
    """Per-file drift state for every fingerprint in ``entry``."""
    results: list[dict[str, object]] = []
    warnings: list[str] = []

    excerpt = entry.excerpt
    tracked = [fp for fp in entry.fingerprints if fp.span is not None]
    if excerpt is not None and tracked and tracked[0].excerpt_sha256:
        if _sha256(excerpt.encode("utf-8")) != tracked[0].excerpt_sha256:
            warnings.append(
                "The logged code block no longer matches its recorded excerpt SHA-256 "
                "(the log was hand-edited); drift was checked against the block as written."
            )

    for fp in entry.fingerprints:
        result: dict[str, object] = {
            "path": fp.path,
            "recorded_span": _span(fp.span),
            "current_span": None,
        }
        target = (root / fp.path).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            result["state"] = FILE_MISSING
        else:
            data = target.read_bytes()
            if _sha256(data) == fp.sha256:
                result["state"] = UNCHANGED
                result["current_span"] = _span(fp.span)
            elif fp.span is None:
                result["state"] = FILE_MODIFIED_NO_EXCERPT
            elif excerpt is None:
                # The entry is damaged, so only the whole-file signal is trustworthy.
                result["state"] = FILE_MODIFIED_NO_EXCERPT
                warnings.append(
                    f"`{fp.path}` changed, but the logged excerpt could not be read, so "
                    "excerpt-level drift is unavailable."
                )
            else:
                try:
                    current = find_excerpt_span(data.decode("utf-8"), excerpt)
                except UnicodeDecodeError:
                    current = None
                if current is None:
                    result["state"] = EXCERPT_MODIFIED_OR_REMOVED
                else:
                    result["state"] = FILE_MODIFIED_EXCERPT_INTACT
                    result["current_span"] = list(current)
        results.append(result)
    return results, warnings


def _drift_warning(item: dict[str, object]) -> str | None:
    state, path = item["state"], item["path"]
    if state == UNCHANGED:
        return None
    if state == FILE_MODIFIED_EXCERPT_INTACT:
        start, end = item["current_span"]  # type: ignore[misc]
        return f"`{path}` changed; the logged excerpt is still present at lines {start}–{end}."
    if state == EXCERPT_MODIFIED_OR_REMOVED:
        return f"`{path}` changed and the logged excerpt is no longer present."
    if state == FILE_MODIFIED_NO_EXCERPT:
        return f"`{path}` changed since this entry was recorded."
    return f"`{path}` is missing since this entry was recorded."


def _validate_limit(limit: object) -> int:
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 50:
        raise CodeStoryValidationError("limit must be an integer from 1 to 50.")
    return limit


def list_change_entries(
    project_root: str, limit: int = 10, *, lock_timeout: float = LOCK_TIMEOUT_SECONDS
) -> dict[str, object]:
    """Most recent entries first, plus any parse warnings."""
    root = _validate_root(project_root)
    limit = _validate_limit(limit)
    parsed = parse_log(_read_log(root, lock_timeout))
    entries = [
        {
            "entry_id": e.entry_id,
            "title": e.title,
            "recorded": e.recorded,
            "malformed": bool(e.problems),
        }
        for e in reversed(parsed.entries)
    ][:limit]
    return {"entries": entries, "total": len(parsed.entries), "warnings": parsed.warnings}


def get_change_entry(
    project_root: str, entry_id: str, *, lock_timeout: float = LOCK_TIMEOUT_SECONDS
) -> dict[str, object]:
    """One entry (matched case-insensitively) with per-file drift states."""
    root = _validate_root(project_root)
    if not isinstance(entry_id, str) or not entry_id.strip():
        raise CodeStoryValidationError("entry_id is required.")
    wanted = entry_id.strip().upper()
    if not _ENTRY_ID_RE.match(wanted):
        raise CodeStoryValidationError(
            f"entry_id must look like CS-YYYYMMDD-<12 hex characters>: {entry_id!r}"
        )

    parsed = parse_log(_read_log(root, lock_timeout))
    matches = [e for e in parsed.entries if e.entry_id == wanted]
    if not matches:
        raise CodeStoryValidationError(
            f"No entry found with ID {wanted}. Use list_changes to see recent IDs."
        )
    entry = matches[0]

    warnings = [w for w in parsed.warnings if wanted in w]
    drift, drift_warnings = file_drift(root, entry)
    warnings.extend(drift_warnings)
    warnings.extend(w for w in map(_drift_warning, drift) if w)
    return {
        "entry_id": entry.entry_id,
        "title": entry.title,
        "recorded": entry.recorded,
        "entry": entry.text,
        "malformed": bool(entry.problems),
        "drift": drift,
        "drift_note": DRIFT_NOTE,
        "warnings": warnings,
    }
