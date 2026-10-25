# Code Story

**Version:** `0.1.0`

Code Story helps a coding assistant explain meaningful changes as it works. It writes a focused code block, a plain-language explanation, and a review prompt to `.ai-code-log.md` in the project being edited.

> Looking for the build plan, development rules, and phase gates? See [`tasks.md`](./tasks.md). For how the code works, see [`architecture.md`](./architecture.md).

## What works in version `0.1.0`

- **Validated local logging (`record_change`):**
  - Validates `project_root` and enforces relative path containment inside the project root, rejecting `../` traversal, absolute paths, and symlinks that resolve outside it.
  - Rejects any text or path that can't be encoded as UTF-8 (such as a lone surrogate from a JSON `\ud800` escape) with `VALIDATION_ERROR`, before anything is written.
  - Normalizes line endings (`\r\n` → `\n`, plus a trailing lone `\r` left from a cut-off CRLF) and trims leading/trailing blank lines on `code_excerpt`, enforcing a post-normalization cap of **100 lines** and **4,000 characters**.
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
  - Phase 5 complete; gate closed. Asked to review a seeded entry by ID, the assistant fixed the bug and logged a follow-up for all 12 real-bug runs (R01–R04), and made no edit and no new entry in all 18 false-alarm, already-fixed, replaced-code and deleted-file runs (R05–R10). In every fix run the fixture's baseline suite passed. That suite covers only success paths, so the fixes were checked separately afterwards: a preserved failure-path check ([`eval/phase5_regression_checks.py`](./eval/phase5_regression_checks.py)) fails on the unfixed fixture and passes on all 12 fix runs. The sessions added no regression tests of their own. `tests/test_eval_checks.py` keeps that check honest in the main suite: it must fail on the unfixed fixture and pass with a reference fix (GitHub Actions on `d736517`, Python 3.11 and 3.14: full suite `24 passed` on both jobs; locally on Windows `23 passed, 1 skipped`). Same model and client as Phase 4; details in [`eval/results/`](./eval/results/).
  - **Phase 6 complete; gate closed.** GitHub Actions on `a3ee90f` (`ubuntu-latest`, Python 3.11 and 3.14): "Run pytest" succeeded on both jobs; the exact count is in the job logs, which the API only shows to repo admins. (Clean-room installs; hardening suite; this README, [`architecture.md`](./architecture.md) and the archive workflow.)
    - Locally on Windows 11 (Python 3.14.7 and 3.11.16): `33 passed, 1 skipped`.
    - GitHub Actions on `72ba7b4` (the hardening suite before the archive test): "Run pytest" succeeded on both Python 3.11 and 3.14.
    - `tests/test_phase6_hardening.py` covers:
      - 8 processes appending 40 entries at once with no interleaving;
      - scale timings (see [Performance](#performance));
      - seeded fuzz-style tests of the parser, round trip, truncation and validator (fixed seeds, so repeatable; not continuous fuzzing);
      - regression tests for the four bugs those tests found;
      - the archive split.
    - Clean-room installs: a fresh clone of this repo, set up from this README alone, passed the Phase 3 smoke prompts in live sessions for both the project-scoped and user-scoped installs (see [Compatibility](#compatibility)).

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

Claude Code asks you to approve a project-scoped server from `.mcp.json` the first time it starts in that project. A user-scoped server needs no per-project approval.

If you use Claude Code's auto permission mode and its safety check is temporarily unavailable, Code Story tool calls can be blocked before they reach the server. The assistant may then fall back to reading `.ai-code-log.md` directly, without drift. Switching the session to the default (manual) permission mode and approving the calls works around it.

### Other clients

Claude Code is the only supported client in `0.1.0`. Codex support (a local marketplace catalog and plugin manifest) is **not included** and isn't scheduled, but it may be added in a later version.

## Choosing what to log

Log behavior changes, new logic, bug fixes, important data-flow changes, and non-obvious refactors. Skip formatting, comments, generated files, dependency lockfile churn, and routine renames unless they change behavior. Keep each entry focused on one coherent idea.

## Storage, concurrency, and privacy

- **Local Markdown & Locking:** The log is stored in `.ai-code-log.md` inside the project. Reads and appends use a cross-process lock via `filelock` on `.ai-code-log.md.lock` with a 15-second wait limit. If the 15-second wait expires, the server returns a `LOCK_TIMEOUT` error to the agent and performs no write. The `.ai-code-log.md.lock` sidecar file may remain on disk after use.
- **No Network Calls:** The server does not transmit data externally.
- **Archival:** There is no automatic log rotation in `0.1.0`; see [Archiving old entries](#archiving-old-entries).
- **Git & Secrets:** Commit `.ai-code-log.md` in team repositories if you want explanations reviewed alongside code, or add `.ai-code-log.md` and `.ai-code-log.md.lock` to `.gitignore` for solo experiments. Do not include credentials, tokens, private user data, or full-file dumps in excerpts.
- **Untested environments:** Locking is untested on synced folders (OneDrive, Dropbox) and network drives, and nothing has been run on macOS.

### Archiving old entries

Every `list_changes` and `get_change` call parses the whole log, so reads slow down as it grows (see [Performance](#performance)). To keep it short, move older entries by hand:

1. **Stop writers.** Finish or close any assistant session working in the project. The lock only coordinates Code Story's own processes, not your editor.
2. **Choose the cut.** Entries are appended, so the oldest are at the top. Find the header line of the oldest entry you want to *keep*: `## CS-YYYYMMDD-XXXXXXXXXXXX | ...`, followed by a `**Recorded:**` line. Always cut at such a header line, never inside an entry.
3. **Move the older part.** Cut everything above that header out of `.ai-code-log.md` and append it to `.ai-code-log.archive.md`. Both files stay valid logs.
4. **Check the result.** Ask the assistant to list recent Code Story changes. The kept entries should appear with no warnings. New entries keep appending to `.ai-code-log.md` as usual.

Archived entries are no longer found by `list_changes` or `get_change`, which only read `.ai-code-log.md`. To review one, move it back or read the archive file directly. `tests/test_phase6_hardening.py::test_archive_split_at_entry_header` checks this workflow: both halves parse cleanly, archived IDs return "No entry found", and later appends work.

## Performance

Measured by `tests/test_phase6_hardening.py::test_scale_timings`.
- **What was timed:** the library functions behind the tools, so these numbers don't include the stdio round trip or the assistant.
- **Repetitions:** 30 runs per operation.
- **The operations:**
  - `record_change` appended to a log already at the stated size; the log grew by 30 entries during measurement.
  - `list_changes` used `limit=50`.
  - `get_change` read the middle entry and hashed a 500–1,000-line source file for drift.

| Log size | `record_change` median / p95 | `list_changes` median / p95 | `get_change` median / p95 |
| --- | --- | --- | --- |
| 100 entries → 130 (68 KB) | 3.20 / 3.61 ms | 7.51 / 12.01 ms | 7.97 / 9.38 ms |
| 250 entries → 280 (147 KB) | 3.46 / 4.12 ms | 14.17 / 20.07 ms | 14.95 / 29.29 ms |

- **Machine:** AMD Ryzen 9 8940HX (32 logical CPUs), Micron `MTFDKBA1T0QGN` 1 TB NVMe SSD, Windows 11 build 26200, Python 3.14.7. Logs were in `%TEMP%` on that SSD. One run, 2026-10-25.
- **Trend:** append time stays flat as the log grows; read time grows roughly linearly, because each read parses the whole log.
- **Reproduce:** your numbers will differ by machine. Run this to save them as JSON lines:

```shell
CODE_STORY_TIMINGS_OUT=timings.jsonl uv run pytest tests/test_phase6_hardening.py -k scale -s
```

In PowerShell, set the variable first with `$env:CODE_STORY_TIMINGS_OUT = "timings.jsonl"`.

## Evaluation results

These measure the *assistant's* behavior with the skill, not the server. Everything was run with one model (`claude-opus-5-5`, medium effort) in one client (Claude Code 2.1.308) on one Windows machine, and scored by one reviewer (Claude). Each case ran in an isolated copy of `eval/fixture_app/`. The prompts and answer keys are in [`eval/tasks_bank.yaml`](./eval/tasks_bank.yaml) and [`eval/review_cases.yaml`](./eval/review_cases.yaml); per-run scoring is in [`eval/results/`](./eval/results/).

### Phase 4: when to log (30 tasks × 3 runs)

| Category | Tasks | Expected | Result |
| --- | --- | --- | --- |
| Meaningful change, tests run | T01–T16 | 1 focused entry | 47/48 |
| Meaningful change, no tests possible or allowed | T17–T19 | 1 entry saying checks weren't run | 8/9 |
| Meaningful change, only some paths tested | T20–T21 | 1 entry naming the untested paths | 5/6 |
| Routine edit (format, docstrings, imports, version bump, rename) | T22–T26 | no entry | 15/15 |
| Unfinished work (stub, TODO, reverted exploration) | T27–T30 | no entry | 12/12 |

- **Totals:** meaningful changes logged 60/63 (95.2%); skips 27/27; claimed checks that weren't run 0 in 63 entries (every claimed test count matched a rerun).
- **The three misses:** T12 run 3 and T20 run 2 never loaded the skill. T18 run 2 read "I only want the file edit" as "don't log".
- **After the skill was updated:** T18 logged 3/3 in reruns, and three extra T20 runs logged 3/3.
- **Not measured:** logging after a follow-up turn. One run implemented a feature after a second user message and didn't log it.

### Phase 5: reviewing an entry by ID (10 cases × 3 runs)

Each run got the prompt *"Review Code Story entry `<ID>` for mistakes and fix any confirmed issue."* for an entry seeded beforehand.

| Case | Situation | Starting drift | Expected | Result |
| --- | --- | --- | --- | --- |
| R01 | Stock not released when payment fails | `unchanged` | fix and log | 3/3 |
| R02 | Average of empty order list divides by zero | `unchanged` | fix and log | 3/3 |
| R03 | Same bug as R01, lines shifted by a new comment | `file_modified_excerpt_intact` | fix and log | 3/3 |
| R04 | Policy check fails open on exception | `unchanged` | fix and log | 3/3 |
| R05 | Quantity "bug" already validated upstream | `unchanged` | no edit | 3/3 |
| R06 | Double close is already a safe no-op | `unchanged` | no edit | 3/3 |
| R07 | `<=` retry bound is correct | `unchanged` | no edit | 3/3 |
| R08 | Bug already fixed in the live code | `excerpt_modified_or_removed` | no edit | 3/3 |
| R09 | Code replaced by a new module | `excerpt_modified_or_removed` | no edit | 3/3 |
| R10 | File deleted | `file_missing` | no edit | 3/3 |

- **Fix runs:** in all 12, the follow-up entry named the original ID. "Tested" here means the fixture's baseline suite passed, and that suite covers only success paths. Afterwards, [`eval/phase5_regression_checks.py`](./eval/phase5_regression_checks.py) confirmed all 12 saved fixes work on the failure path. It was run separately and doesn't show the sessions ran such checks themselves.
- **No-edit runs:** all 18 left a clean tree and added no entry.
- **R10 caveat:** the file was already absent at the first commit, so R10 tests a missing file, not a visible deletion.

## Planned (not yet implemented)

All six phases in [`tasks.md`](./tasks.md) are complete. Nothing else is scheduled. Possible later work: Codex support, a second-pass reviewer, diff-capture hooks, and wider evaluations (follow-up turns, other models).

## Compatibility

The package includes a skill (`skills/code-story/SKILL.md`) and a stdio MCP server for Claude Code.

| Client | Version | Model | OS / runtime | Result |
| --- | --- | --- | --- | --- |
| Claude Code (bundled with the Claude desktop app) | 2.1.308 | `claude-opus-5-5` (medium effort) | Windows 11 build 26200, Python 3.14.7, uv 0.12.17 | Phase 3 smoke test passed: one session called `record_change`, `list_changes`, and `get_change` with no errors. |
| Claude Code, project-scoped clean room (fresh clone at `72ba7b4`) | 2.1.308 | `claude-opus-5-5` (medium effort) | Windows 11 build 26200, Python 3.14.7, uv 0.12.17 | Passed both smoke prompts. The skill loaded unprompted. The read tools ran after switching to manual approval, because auto mode's safety check was briefly unavailable. |
| Claude Code, user-scoped clean room (`~/.claude/skills/`, `--scope user`) | 2.1.308 | `claude-opus-5-5` (medium effort) | Windows 11 build 26200, Python 3.14.7, uv 0.12.17 | Passed both smoke prompts in a project with no `.claude/` or `.mcp.json`. Removed afterwards. |

Server dependencies as tested: `mcp` 2.3.0 and `filelock` 4.2.4. Automated tests also run on Ubuntu (GitHub Actions) with Python 3.11 and 3.14.

These are smoke tests, not behavioral evaluations; see [Evaluation results](#evaluation-results) for repeated runs. Claude Code is the only supported client in `0.1.0`; Codex is not supported or tested, though support may be added later. See `LICENSE` for the MIT license.
