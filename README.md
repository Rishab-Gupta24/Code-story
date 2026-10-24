# Code Story

**Version:** `0.1.0`

Code Story helps a coding assistant explain meaningful changes as it works. It writes a focused code block, a plain-language explanation, and a review prompt to `.ai-code-log.md` in the project being edited.

> Looking for the build plan, development rules, and phase gates? See [`tasks.md`](./tasks.md).

## What works in version `0.1.0`

- **Validated local logging (`record_change`):**
  - Validates `project_root` and enforces relative path containment inside the project root, rejecting `../` traversal, absolute paths, and symlinks that resolve outside it *(symlink test not yet run on a platform that allows symlinks; see test status)*.
  - Normalizes line endings (`\r\n` → `\n`) and trims leading/trailing blank lines on `code_excerpt`, enforcing a post-normalization cap of **100 lines** and **4,000 characters**.
  - Verifies at record time that the normalized `code_excerpt` exists in at least one listed source file, recording the first match's 1-based line span (`lines <start>–<end>`) and normalized excerpt SHA-256 alongside each file's whole-file SHA-256.
  - Scans inputs for common secret patterns: hard-rejects high-confidence tokens (`sk-`, `AKIA`/`ASIA`, `gh[pousr]_`, `xox[baprs]-`, `-----BEGIN ... PRIVATE KEY-----`) and returns a non-blocking warning on generic `password = "..."` or `api_key = "..."` assignments. Pattern checks reduce accidental leaks of common token formats but cannot catch every secret.
  - Chooses an outer Markdown code fence longer than any backtick run inside `code_excerpt` and ensures clean entry separation even if `.ai-code-log.md` was hand-edited without a trailing newline.
  - Serializes writes with a 15-second cross-process lock (`.ai-code-log.md.lock`), returning `LOCK_TIMEOUT` with no write if the wait expires.
- **Basic retrieval (`list_changes`, `get_change`):** implemented, not yet covered by automated tests (Phase 2). `get_change` warns when a recorded file's whole-file hash changed or the file is missing.
- **Automated test status:** Phase 1 implemented. `tests/test_phase1_log.py` run locally on Windows 11 with Python 3.11.16 and 3.14.7: `7 passed, 1 skipped` on both. `test_reject_symlink_escape` was skipped because Windows refused to create the symlink (Developer Mode off). The Phase 1 gate stays open until that test passes in Linux CI.

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

### Current drift behavior (`0.1.0`)

At logging time, `record_change` stores each listed file's whole-file SHA-256 hash (plus the matched excerpt's line span and excerpt SHA-256). When `get_change` runs today, it recomputes the **whole-file SHA-256 hash** and warns whenever a recorded source file has changed or been removed since logging. This whole-file check is a signal about where to look; five-state excerpt-level drift reporting is scheduled for Phase 2.

## MCP tools

| Tool | Inputs | Output |
| --- | --- | --- |
| `record_change` | `project_root`, `summary`, `explanation`, `reason`, `files`, `code_excerpt`, `checks`, `review_question`, optional `code_language` | Validates inputs, verifies excerpt presence in source, appends one entry to `.ai-code-log.md`, and returns its ID, log path, and any non-blocking warnings. |
| `list_changes` | `project_root`, optional `limit` (1–50) | Recent entry IDs and titles. |
| `get_change` | `project_root`, `entry_id` | Full entry, with a warning if any recorded source file changed or disappeared. |

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

### Codex

Codex packaging (a local marketplace catalog and plugin manifest) is **not in the repository yet**. It will be added and verified when Codex is installed in Phase 3 or Phase 6.

## Choosing what to log

Log behavior changes, new logic, bug fixes, important data-flow changes, and non-obvious refactors. Skip formatting, comments, generated files, dependency lockfile churn, and routine renames unless they change behavior. Keep each entry focused on one coherent idea.

## Storage, concurrency, and privacy

- **Local Markdown & Locking:** The log is stored in `.ai-code-log.md` inside the project. Reads and appends use a cross-process lock via `filelock` on `.ai-code-log.md.lock` with a 15-second wait limit. If the 15-second wait expires, the server returns a `LOCK_TIMEOUT` error to the agent and performs no write. The `.ai-code-log.md.lock` sidecar file may remain on disk after use.
- **No Network Calls:** The server does not transmit data externally.
- **Archival:** There is no automatic log rotation in `0.1.0`. For long-running projects, move older complete entries to an archive file (such as `.ai-code-log.archive.md`) and keep `.ai-code-log.md` short. Lookup tools search `.ai-code-log.md` only.
- **Git & Secrets:** Commit `.ai-code-log.md` in team repositories if you want explanations reviewed alongside code, or add `.ai-code-log.md` and `.ai-code-log.md.lock` to `.gitignore` for solo experiments. Do not include credentials, tokens, private user data, or full-file dumps in excerpts.

## Planned (not yet implemented)

The capabilities below are scheduled for upcoming phases in [`tasks.md`](./tasks.md) and will move to **What works** only after each phase's verification gate passes:

- **Parser recovery for hand-edited or truncated logs (Phase 2):** Isolate malformed or truncated middle/trailing entries during `list_changes` and `get_change` so manual edits to `.ai-code-log.md` never break retrieval, and enforce case-insensitive `entry_id` lookup with automated tests.
- **Per-file five-state drift detection in `get_change` (Phase 2):** Distinguish `unchanged`, `file_modified_excerpt_intact` (with updated line span), `excerpt_modified_or_removed`, `file_modified_no_excerpt` (for secondary files in multi-file entries that did not contain the excerpt), and `file_missing`.
- **Codex packaging (Phase 3 or 6):** Local marketplace catalog and plugin manifest for installing Code Story in Codex.
- **Live client smoke tests & behavioral evaluations (Phases 3–6):** End-to-end client verification, multi-run logging/review evaluations on `eval/fixture_app/`, concurrency/scale benchmarks, and optional post-Phase 6 exploration (second-pass reviewer, diff-capture hooks).

## Compatibility

The package includes a skill (`skills/code-story/SKILL.md`) and a stdio MCP server for Claude Code. It has **not yet been tested** with specific Codex or Claude Code versions; exact client and runtime versions will be recorded in Phase 3 and Phase 6. See `LICENSE` for the MIT license.
