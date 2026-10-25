"""Validated, append-only logging to ``<project_root>/.ai-code-log.md``.

``record_change_entry`` validates inputs, verifies the excerpt against the
source on disk, scans for secrets, and appends one entry under a file lock.
Reading the log back lives in ``code_story.review``.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePath

from filelock import FileLock, Timeout

LOG_FILENAME = ".ai-code-log.md"
LOCK_FILENAME = ".ai-code-log.md.lock"
LOCK_TIMEOUT_SECONDS = 15.0
MAX_EXCERPT_LINES = 100
MAX_EXCERPT_CHARS = 4000

SECRET_SCAN_DISCLAIMER = (
    "Pattern scanning reduces accidental leaks of common token formats "
    "but cannot catch every secret."
)

# High-confidence credential formats: reject the call outright.
_HARD_SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("API key (sk-...)", re.compile(r"sk-[A-Za-z0-9_-]{16,}")),
    ("AWS access key ID", re.compile(r"(?:AKIA|ASIA)[0-9A-Z]{16}")),
    ("GitHub token", re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}")),
    ("Slack token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("PEM private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
]

# Generic assignments: warn only, so test fixtures can still be logged.
_SOFT_SECRET_PATTERN = re.compile(
    r"""(?i)\b(password|passwd|api[_-]?key|secret)\s*[:=]\s*["'][^"'\n]+["']"""
)

_REQUIRED_TEXT_FIELDS = (
    "summary",
    "explanation",
    "reason",
    "code_excerpt",
    "checks",
    "review_question",
)

_CODE_LANGUAGE_RE = re.compile(r"^[A-Za-z0-9_+#.-]*$")


class CodeStoryError(Exception):
    """Base error; ``code`` is the structured error code returned to agents."""

    code = "CODE_STORY_ERROR"


class CodeStoryValidationError(CodeStoryError, ValueError):
    code = "VALIDATION_ERROR"


class LockTimeoutError(CodeStoryError):
    code = "LOCK_TIMEOUT"


@dataclass
class RecordResult:
    entry_id: str
    log_path: str
    warnings: list[str] = field(default_factory=list)


@dataclass
class _FileFingerprint:
    path: str
    sha256: str
    span: tuple[int, int] | None = None


def normalize_excerpt(text: str) -> str:
    """Normalize line endings and trim leading/trailing blank lines only."""
    text = text.replace("\r\n", "\n")
    if text.endswith("\r"):
        # The remains of a CRLF line ending cut off before its "\n".
        text = text[:-1]
    lines = text.split("\n")
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def find_excerpt_span(file_text: str, excerpt: str) -> tuple[int, int] | None:
    """Return the 1-based line span of the first occurrence, or None."""
    haystack = file_text.replace("\r\n", "\n")
    index = haystack.find(excerpt)
    if index == -1:
        return None
    start = haystack.count("\n", 0, index) + 1
    return start, start + excerpt.count("\n")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _require_utf8(name: str, value: str) -> None:
    """Reject text the log can't store, such as lone surrogates from JSON escapes."""
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise CodeStoryValidationError(
            f"{name} contains characters that can't be encoded as UTF-8 "
            f"(position {exc.start}); remove them and retry."
        ) from exc


def _validate_root(project_root: object) -> Path:
    if not isinstance(project_root, str) or not project_root.strip():
        raise CodeStoryValidationError("project_root is required.")
    _require_utf8("project_root", project_root)
    root = Path(project_root)
    if not root.is_absolute():
        raise CodeStoryValidationError(
            f"project_root must be an absolute path: {project_root!r}"
        )
    if not root.is_dir():
        raise CodeStoryValidationError(
            f"project_root is not an existing directory: {project_root!r}"
        )
    return root.resolve()


def _validate_files(root: Path, files: object) -> list[tuple[str, Path]]:
    if not isinstance(files, list) or not files:
        raise CodeStoryValidationError("files must be a non-empty list of paths.")
    validated: list[tuple[str, Path]] = []
    seen: set[str] = set()
    for raw in files:
        if not isinstance(raw, str) or not raw.strip():
            raise CodeStoryValidationError("files entries must be non-empty strings.")
        _require_utf8("files entry", raw)
        if PurePath(raw).is_absolute() or Path(raw).is_absolute():
            raise CodeStoryValidationError(
                f"files entries must be relative to project_root: {raw!r}"
            )
        resolved = (root / raw).resolve()
        if not resolved.is_relative_to(root):
            raise CodeStoryValidationError(
                f"File path escapes project_root: {raw!r}"
            )
        if not resolved.is_file():
            raise CodeStoryValidationError(f"File does not exist: {raw!r}")
        display = Path(os.path.normpath(raw)).as_posix()
        if display not in seen:
            seen.add(display)
            validated.append((display, resolved))
    return validated


def _scan_secrets(fields: dict[str, str]) -> list[str]:
    for name, value in fields.items():
        for label, pattern in _HARD_SECRET_PATTERNS:
            if pattern.search(value):
                raise CodeStoryValidationError(
                    f"{name} appears to contain a {label}. Remove or redact it "
                    f"and retry. {SECRET_SCAN_DISCLAIMER}"
                )
    warnings = []
    for name, value in fields.items():
        match = _SOFT_SECRET_PATTERN.search(value)
        if match:
            warnings.append(
                f"{name} contains a possible credential assignment "
                f"({match.group(1)} = \"...\"). Redact and retry if it is a real "
                f"secret. {SECRET_SCAN_DISCLAIMER}"
            )
    return warnings


def _code_fence(excerpt: str) -> str:
    longest = max((len(run) for run in re.findall(r"`+", excerpt)), default=0)
    return "`" * max(3, longest + 1)


def _format_entry(
    entry_id: str,
    recorded: str,
    summary: str,
    explanation: str,
    reason: str,
    fingerprints: list[_FileFingerprint],
    excerpt: str,
    excerpt_sha: str,
    code_language: str,
    checks: str,
    review_question: str,
) -> str:
    files_line = ", ".join(f"`{fp.path}`" for fp in fingerprints)
    fingerprint_lines = []
    for fp in fingerprints:
        if fp.span is None:
            detail = "no excerpt tracked"
        else:
            detail = f"lines {fp.span[0]}–{fp.span[1]}, excerpt SHA-256: `{excerpt_sha}`"
        fingerprint_lines.append(f"- `{fp.path}`: `{fp.sha256}` ({detail})")
    fence = _code_fence(excerpt)
    quoted = "\n".join(f"> {line}".rstrip() for line in review_question.split("\n"))
    return (
        f"## {entry_id} | {summary}\n"
        f"\n"
        f"**Recorded:** {recorded}  \n"
        f"**Files:** {files_line}\n"
        f"\n"
        f"**Source fingerprints (SHA-256):**\n"
        + "\n".join(fingerprint_lines)
        + f"\n"
        f"\n"
        f"### What this does\n"
        f"\n"
        f"{explanation}\n"
        f"\n"
        f"### Why it changed\n"
        f"\n"
        f"{reason}\n"
        f"\n"
        f"### Code\n"
        f"\n"
        f"{fence}{code_language}\n"
        f"{excerpt}\n"
        f"{fence}\n"
        f"\n"
        f"### Checks\n"
        f"\n"
        f"{checks}\n"
        f"\n"
        f"### Review prompt\n"
        f"\n"
        f"{quoted}\n"
    )


def _separator_for(existing: bytes) -> str:
    """Blank-line separator so a new entry starts on a clean boundary."""
    if not existing:
        return ""
    if existing.endswith(b"\n\n") or existing.endswith(b"\r\n\r\n"):
        return ""
    if existing.endswith(b"\n"):
        return "\n"
    return "\n\n"


def record_change_entry(
    project_root: str,
    summary: str,
    explanation: str,
    reason: str,
    files: list[str],
    code_excerpt: str,
    checks: str,
    review_question: str,
    code_language: str = "",
    *,
    lock_timeout: float = LOCK_TIMEOUT_SECONDS,
) -> RecordResult:
    """Validate inputs and append one entry to ``.ai-code-log.md``."""
    root = _validate_root(project_root)

    text_fields = {
        "summary": summary,
        "explanation": explanation,
        "reason": reason,
        "code_excerpt": code_excerpt,
        "checks": checks,
        "review_question": review_question,
    }
    for name in _REQUIRED_TEXT_FIELDS:
        value = text_fields[name]
        if not isinstance(value, str) or not value.strip():
            raise CodeStoryValidationError(f"{name} is required and may not be blank.")
        _require_utf8(name, value)

    if code_language is None:
        code_language = ""
    if not isinstance(code_language, str):
        raise CodeStoryValidationError("code_language must be a string.")
    code_language = code_language.strip()
    if not _CODE_LANGUAGE_RE.match(code_language):
        raise CodeStoryValidationError(
            f"code_language must be a simple identifier: {code_language!r}"
        )

    validated_files = _validate_files(root, files)

    summary = " ".join(summary.split())
    explanation = explanation.replace("\r\n", "\n").strip()
    reason = reason.replace("\r\n", "\n").strip()
    checks = checks.replace("\r\n", "\n").strip()
    review_question = review_question.replace("\r\n", "\n").strip()

    excerpt = normalize_excerpt(code_excerpt)
    excerpt_lines = excerpt.count("\n") + 1
    if excerpt_lines > MAX_EXCERPT_LINES:
        raise CodeStoryValidationError(
            f"code_excerpt has {excerpt_lines} lines after normalization; "
            f"the limit is {MAX_EXCERPT_LINES}. Log a more focused excerpt."
        )
    if len(excerpt) > MAX_EXCERPT_CHARS:
        raise CodeStoryValidationError(
            f"code_excerpt has {len(excerpt)} characters after normalization; "
            f"the limit is {MAX_EXCERPT_CHARS}. Log a more focused excerpt."
        )

    warnings = _scan_secrets(
        {
            "summary": summary,
            "explanation": explanation,
            "reason": reason,
            "code_excerpt": excerpt,
            "checks": checks,
            "review_question": review_question,
        }
    )

    fingerprints: list[_FileFingerprint] = []
    for display, resolved in validated_files:
        data = resolved.read_bytes()
        try:
            file_text = data.decode("utf-8")
        except UnicodeDecodeError:
            file_text = None
        span = find_excerpt_span(file_text, excerpt) if file_text is not None else None
        fingerprints.append(_FileFingerprint(display, _sha256(data), span))
    if all(fp.span is None for fp in fingerprints):
        raise CodeStoryValidationError(
            "code_excerpt was not found in any listed file. Copy the excerpt "
            "exactly from the source on disk."
        )

    now = datetime.now().astimezone()
    entry_id = f"CS-{now:%Y%m%d}-{secrets.token_hex(6).upper()}"
    entry = _format_entry(
        entry_id=entry_id,
        recorded=now.strftime("%Y-%m-%d %H:%M %z"),
        summary=summary,
        explanation=explanation,
        reason=reason,
        fingerprints=fingerprints,
        excerpt=excerpt,
        excerpt_sha=_sha256(excerpt.encode("utf-8")),
        code_language=code_language,
        checks=checks,
        review_question=review_question,
    )

    log_path = root / LOG_FILENAME
    lock = FileLock(str(root / LOCK_FILENAME), timeout=lock_timeout)
    try:
        with lock:
            existing = log_path.read_bytes() if log_path.exists() else b""
            payload = _separator_for(existing) + entry
            with open(log_path, "a", encoding="utf-8", newline="\n") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
    except Timeout as exc:
        raise LockTimeoutError(
            f"Timed out after {lock_timeout:g}s waiting for {LOCK_FILENAME}; "
            "nothing was written."
        ) from exc

    return RecordResult(entry_id=entry_id, log_path=str(log_path), warnings=warnings)


def _read_log(root: Path, lock_timeout: float) -> str:
    log_path = root / LOG_FILENAME
    lock = FileLock(str(root / LOCK_FILENAME), timeout=lock_timeout)
    try:
        with lock:
            if not log_path.exists():
                return ""
            # Decode bytes directly: read_text() would turn a lone "\r" inside a
            # logged excerpt into "\n" and break its SHA-256 and span matching.
            return log_path.read_bytes().decode("utf-8")
    except Timeout as exc:
        raise LockTimeoutError(
            f"Timed out after {lock_timeout:g}s waiting for {LOCK_FILENAME}."
        ) from exc
