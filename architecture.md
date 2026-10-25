# Code Story architecture (`0.1.0`)

This describes the code as it stands at the end of Phase 6. For what is tested and how, see [`README.md`](./README.md) and [`tasks.md`](./tasks.md).

## Overview

Code Story has two halves. They meet only at the MCP tool interface:

- **A skill** (`skills/code-story/SKILL.md`): plain-language instructions telling the coding assistant when to log a change, how to fill in each field honestly, and how to review an entry by ID. The skill is the only part that shapes the assistant's *behavior*, and Phases 4 and 5 measured it.
- **A stdio MCP server** (`src/code_story/`): deterministic Python that validates entries, appends them to `<project_root>/.ai-code-log.md`, and reads them back with drift detection. It never calls the network and never edits source code.

```text
coding assistant ──(skill tells it when/how)──► MCP tools over stdio
                                                  │
           server.py  record_change / list_changes / get_change
              │                 │
           log.py           review.py
   validate → fingerprint   parse → drift
        → lock → append       (reads under the same lock)
              │                 │
              └──► <project_root>/.ai-code-log.md (+ .ai-code-log.md.lock)
```

## Modules

| Module | Responsibility |
| --- | --- |
| `server.py` | Registers the three tools on an `MCPServer("code-story")` (MCP Python SDK 2.x) and runs it over stdio. Each tool calls one library function and turns any `CodeStoryError` into `{"ok": false, "error": <code>, "message": ...}`. Success responses are `{"ok": true, ...}`. |
| `log.py` | Input validation, excerpt normalization and matching, secret scanning, entry formatting, and the locked append (`record_change_entry`). Also the shared locked read (`_read_log`). |
| `review.py` | Fence-aware log parser with recovery (`parse_log`), per-file drift (`file_drift`), and the two read tools (`list_change_entries`, `get_change_entry`). |

Errors: `CodeStoryError` (code `CODE_STORY_ERROR`) is the base class. `CodeStoryValidationError` (`VALIDATION_ERROR`, also a `ValueError`) covers bad input. `LockTimeoutError` (`LOCK_TIMEOUT`) means the lock wait expired.

## Writing an entry (`record_change`)

`record_change_entry` runs these steps in order and writes nothing unless every one passes:

1. **Project root:** must be a non-blank absolute path to an existing directory. It is then resolved, following symlinks.
2. **Text fields:** `summary`, `explanation`, `reason`, `code_excerpt`, `checks` and `review_question` must be non-blank strings. All text, including paths, must be encodable as UTF-8; this rejects lone surrogates from JSON escapes. `code_language` must be a string of `[A-Za-z0-9_+#.-]`.
3. **Files:** a non-empty list of relative paths. Each is resolved against the root and must stay inside it (`resolve().is_relative_to(root)`), so `../` and symlinks pointing outside are rejected. Each must be an existing file. Duplicates are dropped, and paths are stored in POSIX form.
4. **Normalization:**
   - `summary`: whitespace collapsed to single spaces, so it fits on the header line.
   - Other text fields: CRLF becomes LF and the ends are trimmed.
   - `code_excerpt`: CRLF becomes LF, a trailing lone CR is dropped, and blank lines are trimmed from both ends. Inner indentation is kept.
5. **Size caps:** the normalized excerpt may be at most 100 lines and 4,000 characters.
6. **Secret scan:**
   - **Hard reject:** high-confidence token formats anywhere in the text (`sk-…`, `AKIA`/`ASIA…`, `gh[pousr]_…`, `xox[baprs]-…`, PEM private-key headers).
   - **Warn only:** generic `password|passwd|api_key|secret = "…"` assignments, so test fixtures can still be logged.
   - This is pattern matching. It can't catch every secret.
7. **Fingerprints:**
   - Each listed file gets a whole-file SHA-256.
   - The excerpt is searched for in each file, after CRLF→LF on the file side. The first occurrence gives a 1-based line span.
   - At least one file must contain the excerpt, which blocks fabricated excerpts. Files that don't contain it are recorded as "no excerpt tracked".
8. **Formatting:**
   - The ID is `CS-YYYYMMDD-<12 uppercase hex>`: the local date plus `secrets.token_hex(6)`.
   - The timestamp is local time with a numeric offset, `YYYY-MM-DD HH:MM ±HHMM`.
   - The `### Code` fence is backticks, one longer than the longest backtick run in the excerpt (at least 3), so the excerpt can never close it.
9. **Append:**
   - Take the cross-process `FileLock` on `.ai-code-log.md.lock`, waiting up to 15 s. On timeout, raise `LOCK_TIMEOUT` with nothing written.
   - Read the existing bytes and choose a separator, so the new entry starts after a blank line even if the file was hand-edited without a trailing newline.
   - Append the separator and entry in **one** `write()`, then `flush()` and `fsync()`.

Entry layout (the spec is in `tasks.md`):

```text
## <ID> | <summary>

**Recorded:** <timestamp>  
**Files:** `a.py`, `b.py`

**Source fingerprints (SHA-256):**
- `a.py`: `<sha256>` (lines S–E, excerpt SHA-256: `<sha256>`)
- `b.py`: `<sha256>` (no excerpt tracked)

### What this does / ### Why it changed / ### Code (fenced) / ### Checks / ### Review prompt (> quoted)
```

The log is append-only: the server never rewrites or deletes earlier entries.

## Reading the log (`list_changes`, `get_change`)

Both tools read the whole log under the same lock. They decode the raw bytes as UTF-8; `read_text()` isn't used, because its newline translation would turn a lone `\r` inside an excerpt into `\n`. Then they call `parse_log`.

**Finding entries (`_find_headers`):**
- Text is split into lines after CRLF→LF.
- Outside a code fence, any line matching `^## (CS-\d{8}-[0-9A-F]{12}) \| (.+)$` (case-insensitive) starts an entry.
- Fence tracking follows CommonMark: openers have 0–3 spaces of indent and 3+ backticks or tildes, and backtick info strings may not contain backticks. A closer must use the same character and be at least as long.
- A `## CS-…` line *inside* a fence is code, not an entry.
- **Recovery:** if a fence was never closed (a truncated or hand-edited entry), a header inside it counts as a real entry start only when the next non-blank line is a `**Recorded:**` line. The damaged entry ends there, and the entries after it parse normally.

**Parsing one entry (`_parse_entry`):**
- Extracts the `**Recorded:**` value, the fingerprint lines and the first code block under `### Code` (normalized like an excerpt).
- Anything wrong is added to the entry's `problems`, not raised:
  - an unclosed fence;
  - a missing or duplicated `**Recorded:**` line, where a duplicate suggests merged entries;
  - no readable fingerprints;
  - a missing `### Code` section or code block;
  - a missing `### Review prompt` (likely truncation);
  - a damaged `## CS-` line that didn't match the header pattern. Such a line is folded into the preceding entry and flagged there.
- An entry with problems is returned with `malformed: true`, and a warning names its line.
- A duplicate ID gets a warning, and lookups return the first.

**`list_changes`** returns the newest entries first (`limit` 1–50), plus `total` and the parse warnings.

**`get_change`:**
- Validates the ID's shape, upper-cases it and finds the first matching entry.
- Returns the entry's text, `malformed`, per-file drift, the drift note and the warnings that mention it.

## Drift detection (`file_drift`)

For each recorded fingerprint:

| Condition (checked in order) | State |
| --- | --- |
| Path no longer resolves to a file inside the root | `file_missing` |
| Whole-file SHA-256 unchanged | `unchanged` (current span = recorded span) |
| File changed, and this file had no excerpt tracked | `file_modified_no_excerpt` |
| File changed, but the entry's code block couldn't be read (damaged entry) | `file_modified_no_excerpt`, plus a warning |
| File changed and the excerpt is still found (first occurrence) | `file_modified_excerpt_intact` with `current_span` |
| File changed and the excerpt is gone | `excerpt_modified_or_removed` |

If the code block in the log no longer matches its recorded excerpt SHA-256, `get_change` warns that the log was hand-edited. Drift is then checked against the block as written.

Drift states say *where to look*, not whether a bug exists. The skill tells the assistant to read the live source and confirm an issue before editing.

## Concurrency and durability

- Writers and readers on the same project share one `filelock` lock file. That's what keeps 8 processes appending at once from interleaving entries (`tests/test_phase6_hardening.py`). The lock only coordinates Code Story processes. Anything else editing `.ai-code-log.md` isn't excluded, which is why the archive workflow below says to do it with no assistant sessions running.
- Each append is a single `write()` followed by `fsync`. If a process dies mid-write, the expected worst case is a truncated final entry. No test kills a writer mid-append. The tests do show what happens after truncation: the parser keeps the truncated entry, flags it `malformed`, and later appends start cleanly after a blank-line separator.
- Nothing is cached between calls. Every read parses the whole file, so read latency grows roughly linearly with log size (see the README's performance table).

## Design decisions

- **Markdown, not a database:** the log is meant to be read and reviewed by people, in diffs and pull requests. The cost is a tolerant parser instead of a schema.
- **Excerpt must exist in the source:** this blocks invented code. It can't stop an assistant from describing real code inaccurately, so the skill and the evaluations cover that.
- **Two hashes:** the whole-file hash makes "unchanged" exact. The excerpt hash and span let drift tell "the file moved around the code" apart from "the code itself changed".
- **First occurrence wins:** both recording and drift use the excerpt's first occurrence, so a duplicated snippet can report the earlier copy's span.
- **Errors are values:** tools return `ok: false` with a stable error code instead of raising, so the assistant can correct its input and retry.

## Known limitations

- **Recovery heuristic:** if an earlier entry has an unclosed fence *and* a later code block contains a full entry header followed by a `**Recorded:**` line, recovery treats that inner header as real. Logging excerpts of `.ai-code-log.md` itself is the realistic trigger.
- **Lookups:** they search `.ai-code-log.md` only. Archived entries aren't searched.
- **Secret scanning:** pattern-based; recognized formats only.
- **Locking:** untested on synced folders (OneDrive, Dropbox) and network drives. The concurrency test ran in a local temp directory, on Windows and in Linux CI.
- **Platforms:** macOS is untested. Testing so far covers Windows 11 locally and Ubuntu in CI.

## Tests

| Suite | Covers |
| --- | --- |
| `tests/test_phase1_log.py` | Validation, path containment (including symlinks), excerpt caps and matching, secret tiers, fence sizing, hand-edited tails, lock timeout |
| `tests/test_phase2_review.py` | Ordering and limits, empty and missing logs, case-insensitive IDs, all five drift states, fence-aware parsing, recovery from corrupted and truncated entries |
| `tests/test_phase6_hardening.py` | 8-process concurrent appends, scale timings, seeded fuzzing of the parser, round trip, truncation and validator, regression tests for the four fuzz findings, and the archive split |
| `tests/test_eval_checks.py` | Guards `eval/phase5_regression_checks.py` against the fixture |
