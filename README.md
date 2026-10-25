# Code Story

**Version:** `0.1.0`

Code Story helps a coding assistant explain meaningful changes as it works. It writes a focused code block, a plain-language explanation, and a review prompt to `.ai-code-log.md` in the project being edited.

> Looking for the build plan, development rules, and phase gates? See [`tasks.md`](./tasks.md).

## What works in version `0.1.0`

- **Validated local logging (`record_change`):**
  - Validates `project_root` and enforces relative path containment inside the project root, rejecting `../` traversal, absolute paths, and symlinks that resolve outside it.
  - Normalizes line endings (`\r\n` → `\n`) and trims leading/trailing blank lines on `code_excerpt`, enforcing a post-normalization cap of **100 lines** and **4,000 characters**.
  - Verifies at record time that the normalized `code_excerpt` exists in at least one listed source file, recording the first match's 1-based line span (`lines <start>–<end>`) and normalized excerpt SHA-256 alongside each file's whole-file SHA-256.
  - Scans inputs for common secret patterns: hard-rejects high-confidence tokens (`sk-`, `AKIA`/`ASIA`, `gh[pousr]_`, `xox[baprs]-`, `-----BEGIN ... PRIVATE KEY-----`) and returns a non-blocking warning on generic `password = "..."` or `api_key = "..."` assignments. Pattern checks reduce accidental leaks of common token formats but cannot catch every secret.
  - Chooses an outer Markdown code fence longer than any backtick run inside `code_excerpt` and ensures clean entry separation even if `.ai-code-log.md` was hand-edited without a trailing newline.
  - Serializes writes with a 15-second cross-process lock (`.ai-code-log.md.lock`), returning `LOCK_TIMEOUT` with no write if the wait expires.
- **Retrieval and review (`list_changes`, `get_change`):**
  - `list_changes` returns entries newest first (`limit` 1–50) and handles a missing or empty log.
  - Entry IDs match case-insensitively, in the query and in hand-edited headers.
  - The parser tracks code fences, so a `## CS-...` line inside a logged code block is not mistaken for an entry.
  - Hand-edited or truncated entries are kept and flagged `malformed` with a warning saying what is wrong; the entries around them still parse. The parser recovers from an unclosed fence at the next header followed by a `**Recorded:**` line.
  - `get_change` reports a per-file drift state (see below).
- **Automated test status:**
  - Phase 1 complete; gate closed. GitHub Actions (`ubuntu-latest`, Python 3.11 and 3.14): `8 passed` in `tests/test_phase1_log.py` on both jobs, including `test_reject_symlink_escape`. Locally on Windows 11 (Python 3.11.16 and 3.14.7): `7 passed, 1 skipped`, because `test_reject_symlink_escape` skips when Windows refuses symlink creation (Developer Mode off).
  - Phase 2 complete; gate closed. GitHub Actions (`ubuntu-latest`, Python 3.11 and 3.14): full suite `16 passed` on both jobs, including all 8 tests in `tests/test_phase2_review.py`. Locally on Windows 11 (Python 3.11.16 and 3.14.7): `15 passed, 1 skipped` (the Phase 1 symlink skip).
  - Phase 3 complete; gate closed. A live Claude Code session called `record_change`, `list_changes`, and `get_change` over stdio with no errors (see [Compatibility](#compatibility)).
  - Phase 4 complete; gate closed. Across 30 evaluation tasks run 3 times each with `claude-opus-5-5` in Claude Code, the assistant logged meaningful changes with a focused entry 60/63 times (95.2%), skipped routine and unfinished edits 27/27 times, and claimed no checks it didn't run in any of 63 entries. One model and one client only; details in [`eval/results/`](./eval/results/).
  - Phase 5 complete; gate closed. Asked to review a seeded entry by ID, the assistant fixed the bug and logged a follow-up for all 12 real-bug runs (R01–R04), and made no edit and no new entry in all 18 false-alarm, already-fixed, replaced-code and deleted-file runs (R05–R10). In every fix run the fixture's baseline suite passed. That suite covers only success paths, so the fixes were checked separately afterwards: a preserved failure-path check ([`eval/phase5_regression_checks.py`](./eval/phase5_regression_checks.py)) fails on the unfixed fixture and passes on all 12 fix runs. The sessions added no regression tests of their own. Same model and client as Phase 4; details in [`eval/results/`](./eval/results/).

## Example entry

````markdown
## CS-20261024-A1B2C3D4E5F6 | Apply promo before reserving stock

**Recorded:** 2026-10-24 14:10 +0400  
**Files:** `src/cart/checkout.py`

**Source fingerprints (SHA-256):**
- `src/cart/checkout.py`: `c184...` (lines 42–44, excerpt SHA-256: `9f2a...`)

### What this does

Applies the customer's promo code to calculate the final total, reserves the cart items, and charges the card.

### Why it changed

Bundled items were not receiving the promo discount before checkout totals were calculated.

### Code

```python
total = apply_promo(cart, user.promo_code)
reserve_stock(cart.items)
charge(user, total)
```

### Checks

Unit tests for `apply_promo` passed. The payment failure path was not tested.

### Review prompt

> If `charge()` raises an error, is the reserved stock released back to inventory?
````

The assistant should record only checks it actually ran. Fingerprints shown above are abbreviated for readability; `.ai-code-log.md` stores full 64-character SHA-256 values.

## Review a change

Every entry has an ID in the form `CS-YYYYMMDD-<12 hex characters>`. The random suffix keeps same-day entries distinct.

Ask your assistant:

> **“Review Code Story entry `CS-...` for mistakes and fix any confirmed issue.”**

The assistant retrieves the entry via `get_change`, checks the recorded source fingerprint for drift, inspects the live source code on disk, and verifies whether the suspected issue actually exists before editing anything. If it makes a fix, it appends a separate entry so the history stays readable.

### Drift states

At logging time, `record_change` stores each listed file's whole-file SHA-256 hash, plus the matched excerpt's line span and excerpt SHA-256 for files that contain the excerpt. `get_change` compares those against the files on disk and returns one state per file:

| State | Meaning |
| --- | --- |
| `unchanged` | The whole file is identical to when the entry was recorded. |
| `file_modified_excerpt_intact` | The file changed, but the logged excerpt is still there; `current_span` gives its new line range. |
| `excerpt_modified_or_removed` | The file changed and the logged excerpt is no longer in it. |
| `file_modified_no_excerpt` | A secondary file (no excerpt tracked) changed. Also used when the entry is damaged and its excerpt cannot be read. |
| `file_missing` | The file no longer exists inside `project_root`. |

Drift states show where to inspect the live code; they do not say whether a bug is present.

## MCP tools

| Tool | Inputs | Output |
| --- | --- | --- |
| `record_change` | `project_root`, `summary`, `explanation`, `reason`, `files`, `code_excerpt`, `checks`, `review_question`, optional `code_language` | Validates inputs, verifies excerpt presence in source, appends one entry to `.ai-code-log.md`, and returns its ID, log path, and any non-blocking warnings. |
| `list_changes` | `project_root`, optional `limit` (1–50) | Recent entry IDs, titles, timestamps, and a `malformed` flag, newest first, plus parse warnings. |
| `get_change` | `project_root`, `entry_id` (case-insensitive) | Full entry text, per-file drift states with recorded and current line spans, and warnings. |

`project_root` is the absolute path to the project being edited. File paths supplied to `record_change` are relative to that root and may not escape it.

## Install and run

Requires Python 3.11+ and [`uv`](https://docs.astral.sh/uv/). The same commands work in PowerShell, Bash, and zsh:

```shell
uv sync
uv run code-story
```

The server waits on stdio for an MCP client. Stop it with Ctrl+C when running it manually.

If Windows Application Control (Smart App Control) blocks the generated `code-story.exe` launcher, run the server as a module instead: `uv run python -m code_story.server`.

Run the test suite with:

```shell
uv run pytest -v
```

### Claude Code

You can install the skill in a single project (copy `skills/code-story/` into `<project>/.claude/skills/code-story/`) or for your user account across all projects (copy `skills/code-story/` into `~/.claude/skills/code-story/`).

Then register the local MCP server (replace the path with this plugin folder's absolute path):

```shell
claude mcp add --scope project code-story -- uv run --directory /absolute/path/to/code-story code-story
```

*(Use `--scope user` if you installed the skill in `~/.claude/skills/`.)*

On Windows machines where Application Control blocks the generated `code-story.exe` launcher, register the module form instead. This is the command used in the Phase 3 smoke test:

```shell
claude mcp add --scope project code-story -- uv run --directory C:/absolute/path/to/code-story python -m code_story.server
```

Claude Code asks you to approve a project-scoped server from `.mcp.json` the first time it starts in that project.

### Other clients

Claude Code is the only supported client in `0.1.0`. Codex support (a local marketplace catalog and plugin manifest) is **not included** and isn't scheduled, but it may be added in a later version.

## Choosing what to log

Log behavior changes, new logic, bug fixes, important data-flow changes, and non-obvious refactors. Skip formatting, comments, generated files, dependency lockfile churn, and routine renames unless they change behavior. Keep each entry focused on one coherent idea.

## Storage, concurrency, and privacy

- **Local Markdown & Locking:** The log is stored in `.ai-code-log.md` inside the project. Reads and appends use a cross-process lock via `filelock` on `.ai-code-log.md.lock` with a 15-second wait limit. If the 15-second wait expires, the server returns a `LOCK_TIMEOUT` error to the agent and performs no write. The `.ai-code-log.md.lock` sidecar file may remain on disk after use.
- **No Network Calls:** The server does not transmit data externally.
- **Archival:** There is no automatic log rotation in `0.1.0`. For long-running projects, move older complete entries to an archive file (such as `.ai-code-log.archive.md`) and keep `.ai-code-log.md` short. Lookup tools search `.ai-code-log.md` only.
- **Git & Secrets:** Commit `.ai-code-log.md` in team repositories if you want explanations reviewed alongside code, or add `.ai-code-log.md` and `.ai-code-log.md.lock` to `.gitignore` for solo experiments. Do not include credentials, tokens, private user data, or full-file dumps in excerpts.

## Planned (not yet implemented)

The capabilities below are scheduled for upcoming phases in [`tasks.md`](./tasks.md) and will move to **What works** only after each phase's verification gate passes:

- **Hardening and portability (Phase 6):** Clean-room setup checks for project-scoped and user-scoped Claude Code installs, concurrency/scale benchmarks, and fuzz tests.

Possibly later, not scheduled: Codex support, a second-pass reviewer, and diff-capture hooks.

## Compatibility

The package includes a skill (`skills/code-story/SKILL.md`) and a stdio MCP server for Claude Code.

| Client | Version | Model | OS / runtime | Result |
| --- | --- | --- | --- | --- |
| Claude Code (bundled with the Claude desktop app) | 2.1.308 | `claude-opus-5-5` (medium effort) | Windows 11 build 26200, Python 3.14.7, uv 0.12.17 | Phase 3 smoke test passed: one session called `record_change`, `list_changes`, and `get_change` with no errors. |

This is one smoke test in one session, not a behavioral evaluation; Phase 4 measures logging behavior across repeated runs. Claude Code is the only supported client in `0.1.0`; Codex is not supported or tested, though support may be added later. See `LICENSE` for the MIT license.
