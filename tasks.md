# Code Story — Build Plan, Rules, and Verification (`0.1.0`)

**Current Status:** Phase 1 complete; gate closed. GitHub Actions (`ubuntu-latest`, Python 3.11 and 3.14): `8 passed` in `tests/test_phase1_log.py` on both jobs, including `test_reject_symlink_escape`. Locally on Windows 11 (Python 3.11.16 and 3.14.7): `7 passed, 1 skipped`, because `test_reject_symlink_escape` skips when Windows refuses symlink creation (Developer Mode off). Phase 2 complete; gate closed. GitHub Actions (`ubuntu-latest`, Python 3.11 and 3.14): full suite `16 passed` on both jobs, including all 8 tests in `tests/test_phase2_review.py`. Locally on Windows 11 (Python 3.11.16 and 3.14.7): `15 passed, 1 skipped` (the Phase 1 symlink skip). Phase 3 complete; gate closed: a live Claude Code 2.1.308 session (`claude-opus-5-5`) called all three tools without errors (see Phase 3 results).

Build and verify one phase at a time. Do not advance to the next deterministic phase until the current phase's gate is closed.

---

## Development Rules & Architectural Decisions

1. **Sequential Gate Discipline:** For the deterministic engineering phases (**Phase 1, Phase 2, Phase 3, and Phase 6**), do not start the next phase until the current phase's **Done when** condition passes.
2. **Keep `README.md` Honest:** `README.md` must accurately reflect what works and passes tests today—neither overclaiming unbuilt features nor hiding working, tested code. Move items out of the README's **Planned (not yet implemented)** section only after their phase gate passes.
3. **Architecture Documentation Deferred:** Do not maintain a separate `architecture.md` while the phases are still in progress; write `architecture.md` in Phase 6 once the implementation settles.
4. **No Premature Hooks or Autonomous Patching:** Do not add editor hooks, background file watchers, or a second LLM reviewer before the core write/read/review loop is verified end to end.
5. **Log Format Specification:**
   - Every entry header has the form `## CS-YYYYMMDD-XXXXXXXXXXXX | <summary>`.
   - Timestamps use local time with full 4-digit UTC offset (`YYYY-MM-DD HH:MM ±HHMM`, e.g., `2026-10-24 14:10 +0400`).
   - Entry IDs (`CS-YYYYMMDD-<12 hex chars>`) are generated in uppercase, and in Phase 2 both the parser header regex (`^## (CS-\d{8}-[0-9A-Fa-f]{12}) \| (.+)$` with `re.IGNORECASE`) and `get_change` lookups will be verified to match IDs **case-insensitively** so hand-edited lowercase hex characters still resolve.
   - When formatting the `### Code` block, the server chooses an outer backtick fence strictly longer than the longest contiguous run of backticks inside `code_excerpt` (minimum 3 backticks ```` ``` ````).

````markdown
## CS-YYYYMMDD-XXXXXXXXXXXX | <summary>

**Recorded:** YYYY-MM-DD HH:MM ±HHMM  
**Files:** `path/to/file1.py`, `path/to/file2.py`

**Source fingerprints (SHA-256):**
- `path/to/file1.py`: `<64-char file sha256>` (lines 42–44, excerpt SHA-256: `<64-char excerpt sha256>`)
- `path/to/file2.py`: `<64-char file sha256>` (no excerpt tracked)

### What this does

<explanation>

### Why it changed

<reason>

### Code

```<code_language>
<code_excerpt>
```

### Checks

<checks>

### Review prompt

> <review_question>
````

---

## Phase 1 — Validated local logging and automated tests

**Status:** Phase 1 complete; gate closed. GitHub Actions (`ubuntu-latest`, Python 3.11 and 3.14): `8 passed` in `tests/test_phase1_log.py` on both jobs, including `test_reject_symlink_escape`. Locally on Windows 11 (Python 3.11.16 and 3.14.7): `7 passed, 1 skipped`, because `test_reject_symlink_escape` skips when Windows refuses symlink creation (Developer Mode off).

**Goal:** Make `record_change` validate inputs, verify excerpt presence, check for common secret patterns, and write readable entries to `<project_root>/.ai-code-log.md`, backed by an automated `pytest` suite from day one.

### Work

1. **Environment & Root Validation:**
   - Confirm Python 3.11+ and `uv sync`.
   - Require `project_root` to be an existing absolute directory.
   - Require `files` to be a non-empty list of relative paths that resolve inside `project_root` (`.resolve().is_relative_to(root_path)`) and exist as files on disk. Store paths in Markdown using POSIX slashes (`as_posix()`).
   - Reject missing or whitespace-only required text fields (`summary`, `explanation`, `reason`, `code_excerpt`, `checks`, `review_question`). Strip newlines from `summary`.
2. **Excerpt Normalization, Length Cap & Matching Rules (Implemented):**
   - **Default normalization:** Normalize line endings only (`\r\n` → `\n`) and trim leading and trailing blank lines. Never alter whitespace inside lines, as that can corrupt string literals. *(Optional later refinement: strip a common leading indentation across all lines if needed, using the exact same normalization across matching, hashing, and drift checks.)*
   - **Post-normalization length cap:** Apply the size limit **after** normalization—reject `code_excerpt` if the normalized text exceeds **100 lines** or **4,000 characters** (trimmed leading/trailing blank lines do not count against the limit).
   - Check that the normalized `code_excerpt` appears in at least one file listed in `files`; reject the call if it does not match any listed file.
   - If the excerpt appears more than once in a file, match the **first occurrence** and record its 1-based `start_line`–`end_line` span.
   - Record fingerprint metadata **per file**: whole-file SHA-256 for every listed file, plus `(lines <start>–<end>, excerpt SHA-256: <hash>)` for each file containing the excerpt, or `(no excerpt tracked)` for secondary listed files that do not contain the excerpt.
3. **Secret Pattern Scanning (Implemented):**
   - Scan text inputs for common credential formats. State clearly in error messages and docs that pattern scanning reduces accidental leaks of known formats and cannot catch every secret.
   - **Hard-reject** high-confidence patterns:
     - `sk-[A-Za-z0-9_-]{16,}` (API keys)
     - `(AKIA|ASIA)[0-9A-Z]{16}` (AWS access key IDs)
     - `gh[pousr]_[A-Za-z0-9_]{20,}` (GitHub tokens)
     - `xox[baprs]-[A-Za-z0-9-]{10,}` (Slack tokens)
     - `-----BEGIN [A-Z ]*PRIVATE KEY-----` (PEM private keys)
   - **Warn (do not reject)** on generic assignment patterns like `password = "..."` or `api_key = "..."` so test fixtures still work; return a warning field in the tool response so the assistant can redact and retry if appropriate.
4. **Locking, Single-Write Append & Hand-Edit Tail Recovery (Implemented):**
   - Use `filelock.FileLock` on `<project_root>/.ai-code-log.md.lock` with a **15-second timeout**.
   - If the 15-second wait expires, return a structured `LOCK_TIMEOUT` error to the agent without writing to `.ai-code-log.md`.
   - Format the complete entry in memory, write it in a single `write()` call, then call `flush()` and `os.fsync()`. (Do not claim OS crash atomicity; parser recovery in Phase 2 handles truncated trailing entries.)
   - Ensure that if `.ai-code-log.md` was hand-edited and lacks a trailing newline, the next appended entry still begins on a clean `\n\n## CS-...` boundary.
5. **Phase 1 Automated Test Suite (`tests/test_phase1_log.py` — 8 named tests):**
   - [x] `test_record_two_valid_entries`: PASSED — Records two entries and checks IDs, `±HHMM` timestamps, per-file hashes, excerpt hashes, line spans, and `(no excerpt tracked)` for secondary files.
   - [x] `test_reject_relative_root_and_path_traversal`: PASSED — Rejects a relative `project_root`, `../` traversal, and absolute file paths without changing existing log entries.
   - [x] `test_reject_symlink_escape`: PASSED in Linux CI (skips locally on Windows when symlink creation is refused) — Rejects a symlink pointing outside `project_root` and confirms the log is unchanged.
   - [x] `test_reject_missing_or_blank_fields`: PASSED — Rejects empty/whitespace fields, empty or missing `files`, and blank `project_root` without changing existing log entries; collapses newlines in `summary`.
   - [x] `test_reject_fabricated_excerpt`: PASSED — Rejects an excerpt that does not appear in the named source file, and verifies `
` vs. `
` normalization and duplicate-match first-occurrence behavior.
   - [x] `test_excerpt_caps_and_secret_scanning`: PASSED — Verifies the 100-line / 4,000-character limit applies *after* trimming leading/trailing blank lines; rejects high-confidence tokens (`sk-`, `AKIA`, `ASIA`, `ghp_`, `xoxb-`, private key headers); verifies generic `password = "..."` emits a warning without rejecting.
   - [x] `test_dynamic_backtick_fence_and_hand_edited_tail`: PASSED — Verifies 4- and 5-backtick outer fences when `code_excerpt` contains backtick runs, and a clean `

## CS-...` boundary after manual trailing text.
   - [x] `test_lock_timeout_no_write`: PASSED — Holds `.ai-code-log.md.lock`, triggers `LOCK_TIMEOUT` from both `record_change_entry` and the `record_change` MCP tool, and confirms `.ai-code-log.md` is untouched.
6. **CI Workflow (`.github/workflows/tests.yml`):**
   - Run `uv sync` and `uv run pytest` on `ubuntu-latest` across Python `3.11` and `3.14`.

**Done when:** `uv run pytest tests/test_phase1_log.py` passes all 8 test cases (`test_reject_symlink_escape` passes on at least one supported platform: Linux/macOS CI, Windows with Developer Mode, or an elevated Windows shell. The suite also passes on Python 3.11 (minimum supported) and the latest Python).

---

## Phase 2 — Retrieval, per-file drift detection, and tests

**Status:** Phase 2 complete; gate closed. GitHub Actions (`ubuntu-latest`, Python 3.11 and 3.14): full suite `16 passed` on both jobs, including all 8 tests in `tests/test_phase2_review.py`. Locally on Windows 11 (Python 3.11.16 and 3.14.7): `15 passed, 1 skipped` (the Phase 1 symlink skip).

**Goal:** Make `list_changes` and `get_change` retrieve entries reliably, tolerate hand-edited or truncated logs, and report accurate per-file drift states.

### Work

1. **Fence-Aware & Recovery-Capable Parser (Deliverable: Phase 2):**
   - Track code-fence state while scanning `.ai-code-log.md` so `## CS-...` inside a code block is not treated as a new entry header.
   - Compile the entry header regex with `re.IGNORECASE` (`^## (CS-\d{8}-[0-9A-Fa-f]{12}) \| (.+)$`) and normalize IDs during lookup so both uppercase and hand-edited lowercase entry IDs are found.
   - If a hand-edited or truncated entry has an unclosed fence or malformed structure, recover at the next valid top-level `## CS-... | ` header, isolate the malformed chunk, and include a warning in the response rather than crashing.
2. **Per-File Five-State Drift Detection (Deliverable: Phase 2):**
   - For each file recorded in the entry, evaluate and return one of five states using the exact Phase 1 normalization rules:
     - `unchanged`: Current whole-file SHA-256 matches the recorded file SHA-256.
     - `file_modified_excerpt_intact`: Whole-file SHA-256 changed on a file that tracked the excerpt, and the normalized excerpt still matches in the file (return the updated `start_line`–`end_line` span for the first match).
     - `excerpt_modified_or_removed`: Whole-file SHA-256 changed on a file that tracked the excerpt, and the normalized excerpt is no longer present.
     - `file_modified_no_excerpt`: Whole-file SHA-256 changed on a secondary file that had no excerpt tracked at record time (whole-file-only drift signal).
     - `file_missing`: The file no longer exists inside `project_root`.
   - Document clearly in tool output that drift states indicate *where to inspect*, not whether a bug is present.
3. **Phase 2 Automated Test Suite (`tests/test_phase2_review.py`):**
   - Test `list_changes` pagination (`limit` 1–50) and empty/missing log handling.
   - Test case-insensitive `entry_id` header parsing and lookup in `get_change` (including lowercase hex IDs in the file or query).
   - Test all five per-file drift states (`unchanged`, `file_modified_excerpt_intact` with shifted lines, `excerpt_modified_or_removed`, `file_modified_no_excerpt` on secondary files, and `file_missing`).
   - Test parser recovery when `.ai-code-log.md` contains a hand-edited corrupted middle entry or a truncated trailing entry.
   - Tests in `tests/test_phase2_review.py` (all PASSED in GitHub Actions on Python 3.11 and 3.14, and locally on Python 3.11.16 and 3.14.7):
     - [x] `test_list_changes_order_and_limit`: newest-first order, `limit` 1–50 bounds, structured `VALIDATION_ERROR` from the tool.
     - [x] `test_missing_and_empty_log`: missing, empty, and entry-less logs; malformed `entry_id` queries.
     - [x] `test_case_insensitive_entry_ids`: lowercase queries and hand-lowercased headers both resolve.
     - [x] `test_drift_unchanged_and_excerpt_intact_with_shifted_lines`: `unchanged`, then `file_modified_excerpt_intact` with the shifted span; MCP tool output.
     - [x] `test_drift_removed_secondary_and_missing`: `excerpt_modified_or_removed`, `file_modified_no_excerpt`, `file_missing` in one multi-file entry.
     - [x] `test_fence_aware_parser_ignores_headers_inside_code`: a `## CS-...` line inside a logged code block is not an entry.
     - [x] `test_recovery_from_corrupted_middle_entry`: unclosed fence and damaged header line are flagged; neighbours parse normally.
     - [x] `test_recovery_from_truncated_trailing_entry`: truncated tail is flagged, keeps whole-file drift, and later appends parse cleanly.
4. **Known parser limitation:** if a logged code block itself contains a full entry header followed by a `**Recorded:**` line *and* an earlier entry has an unclosed fence, recovery treats that header as real. Excerpts of `.ai-code-log.md` itself are the realistic trigger.

**Done when:** `uv run pytest tests/test_phase2_review.py` passes, and a developer can list recent IDs, fetch an entry case-insensitively, recover cleanly around a corrupted block, and observe accurate five-state per-file drift results after editing or removing source files.

---

## Phase 3 — First client install and live smoke test

**Goal:** Install the skill and stdio MCP server in the first available coding client (Claude Code if available, otherwise Codex) and verify all three tools work end to end in a live assistant session before running behavioral evaluations.

### Work

1. **Install in First Client:**
   - **If using Claude Code:** Copy `skills/code-story/` to `<project>/.claude/skills/code-story/` (or `~/.claude/skills/code-story/`) and run `claude mcp add --scope project code-story -- uv run --directory /abs/path/to/code-story code-story`.
   - **If using Codex:** Add the Codex marketplace catalog and plugin manifest (not yet in the repository), run `codex plugin marketplace add /abs/path/to/code-story`, and install **Code Story** from the local marketplace source.
2. **Live Smoke Test:**
   - Prompt the assistant to make one small behavior change in a scratch repo and verify it calls `record_change`.
   - Prompt the assistant to list recent changes (`list_changes`) and inspect the recorded entry (`get_change`).
3. **Record Environment Details:**
   - Log the exact OS, Python version, `uv` version, client name, client version, and model ID used for the smoke test.

**Done when:** The primary client invokes `record_change`, `list_changes`, and `get_change` over stdio without path, lock, or schema errors.

### Phase 3 results (2026-10-24)

**Status:** Phase 3 complete; gate closed.

- **Environment:** Windows 11 (build 10.0.26200), Python 3.14.7 (server venv), uv 0.12.17, Claude Code 2.1.308 (the build bundled with the Claude desktop app), model `claude-opus-5-5` at medium effort, auto permission mode.
- **Install:** scratch git repo `C:\Users\LAP\code-story-smoke` (`cart.py`, `test_cart.py`). Copied `skills/code-story/` to `.claude/skills/code-story/` and ran `claude mcp add --scope project code-story -- uv run --directory C:/Users/LAP/OneDrive/Desktop/code-story python -m code_story.server`. The module form was needed because Windows Application Control blocks the `code-story.exe` launcher on this machine. The server was approved for the project with `"enabledMcpjsonServers": ["code-story"]` in `.claude/settings.local.json`.
- **Prompt 1** (no mention of Code Story): *"In `cart.py`, make `add_item` raise `ValueError` when quantity is less than 1, add a test for it in `test_cart.py`, and run the tests with `uv run --with pytest pytest -q`."* The session loaded the `code-story` skill on its own and called `mcp__code-story__record_change`, which wrote `CS-20261024-91742AD34487`. Checked by hand afterwards: the recorded span (lines 3–4) and both file SHA-256 values match the files on disk, the excerpt is the new guard, and the `checks` field matches a rerun (`2 passed`) and says negative and non-integer quantities were not tested. One caveat: the session brief told it to "follow the project's own setup in `.claude/` and `.mcp.json`", which may have nudged it toward the skill.
- **Prompt 2:** *"List recent Code Story changes, then show me the full entry for the latest one."* The session called `mcp__code-story__list_changes`, then `mcp__code-story__get_change`, which returned the entry with both files `unchanged`.
- **Errors:** none (no path, lock, or schema errors).

---

## Phase 4 — Evaluate assistant logging behavior

**Goal:** Measure and tune `skills/code-story/SKILL.md` so the assistant logs meaningful completed changes with focused excerpts and honest check reporting, while skipping routine edits and unfinished work.

### Fixture & Evaluation Protocol

- **Fixture App (`eval/fixture_app/`) and Task Bank (`eval/tasks_bank.yaml`):** `eval/fixture_app/` is a small checkout/inventory service with baseline tests, tracked as plain files in this repository. `eval/tasks_bank.yaml` holds 30 task prompts (T01–T30) and a separate answer key. Every seeded issue was confirmed to reproduce on the unmodified fixture (35/35 probes), and the baseline passes (`6 passed`).
- **Isolated Run Folders:** Never run an evaluation inside this repository. Claude Code loads parent `CLAUDE.md` files, and the answer key sits next to the fixture, so an in-repo run would leak both. For each run:
  1. Copy `eval/fixture_app/` to a fresh folder outside the repository.
  2. Install the skill and MCP server there (as in Phase 3), then `git init` and commit everything, so the starting tree is clean.
  3. Send the task's prompt verbatim, and score against the answer key afterwards.
  4. Reset between runs with `git checkout -- . && git clean -fd` **inside that run folder only** (never an unscoped `git clean -fd` in the root `code-story` repository), or start from a new copy.
- **Repetition & Metadata:** Run every scenario **at least 3 times**. Record the model name, client name, and client version for every run, and report pass rates (e.g., `8/9` runs) rather than single-run pass/fail.
- **Scoring Rubric for a "Focused Entry":**
  1. The `code_excerpt` covers the changed logic without dumping the whole file.
  2. The `explanation` accurately matches what the code does.
  3. The `review_question` names a concrete risk or assumption in the change.

### Step 4A: Core Starter Set (Run First — 7 Scenarios)
Start with this 7-scenario baseline until the end-to-end logging workflow is reliable. In `eval/tasks_bank.yaml` these are T04 (S01), T02 (S02), T05 (S03), T20 (S20), T22 (S11), T24 (S12), and T27 (S16):
- **Meaningful changes (4 scenarios — expect 1 focused entry each; evaluated against the meaningful-changes gate and no-fabricated-checks gate):**
  - **S01 (Bug fix):** Fix off-by-one slice bounds in an order history pagination helper.
  - **S02 (New logic):** Add promo discount calculation with a maximum discount cap.
  - **S03 (Validation guard):** Reject negative item quantities at the cart API boundary.
  - **S20 (Meaningful change with checks partially run):** Add both a success handler and a timeout fallback, run only the happy-path unit test, and verify the assistant logs 1 focused entry whose `checks` field explicitly states the timeout path was not tested.
- **Routine / formatting edits (2 scenarios — expect 0 entries):**
  - **S11 (Formatting only):** Run `ruff format` across `eval/fixture_app/`.
  - **S12 (Comments/docstrings only):** Add docstrings without changing executable code.
- **Unfinished work (1 scenario — expect 0 entries):**
  - **S16 (Unfinished stub):** Add a stub function raising `NotImplementedError` while asking the user a clarifying question.

### Step 4B: Expanded Suite (Expand After Starter Set Passes — up to 21 Scenarios)
Once Step 4A is stable across 3+ runs per scenario, expand toward the full 21-scenario set:
- **Additional Meaningful Changes (S04–S10 — expect 1 entry each):** Ownership check before delete (`S04`), float-to-integer cents refactor (`S05`), webhook idempotency check (`S06`), prevent `cancelled` → `shipped` state transition (`S07`), expired session token guard (`S08`), recursive-to-iterative traversal (`S09`), profile cache invalidation (`S10`).
- **Additional Meaningful Changes Where Checks Were Not Run (S19, S21 — expect 1 entry each with honest unverified check status):** Environment missing test DB (`S19`), user explicitly asks not to run `pytest` (`S21`).
- **Additional Routine Edits (S13–S15 — expect 0 entries):** Import sorting (`S13`), lockfile/dependency bump (`S14`), trivial local loop variable rename (`S15`).
- **Additional Unfinished Work (S17–S18 — expect 0 entries):** Mid-refactor syntax error (`S17`), reverted exploration (`S18`).

**Done when (Phase 4 Gates across ≥3 runs per scenario):**
- Meaningful changes (`S01–S10`, `S19–S21`) logged with 1 focused entry (per rubric): **≥90%** pass rate.
- Routine edits (`S11–S15`) and unfinished work (`S16–S18`) skipped (0 entries): **≥90%** pass rate.
- **No fabricated checks** across all logged entries (especially `S19–S21`): **100%** required across all runs.

---

## Phase 5 — Evaluate the review and fix loop

**Goal:** Measure whether pointing the assistant to an entry ID causes it to verify live code, fix confirmed bugs with a follow-up entry, and make **zero speculative edits** on false alarms or stale entries.

### Evaluation Protocol & Starter Set

Use an isolated run folder copied from `eval/fixture_app/` (see Phase 4) and reset it before each run, run each case **at least 3 times**, and record client, client version, and model ID.

#### Step 5A: Core Starter Review Cases (Run First — 2 Cases)
- **R01 (Seeded Bug Violating Fixture Checkout Contract):**
  - *Fixture contract:* `eval/fixture_app/src/cart/checkout.py` documents and requires a two-step reservation model: reserve stock before calling `charge()`, and **call `release_stock()` in an exception handler if `charge()` fails**.
  - *Seeded bug:* Record an entry where `reserve_stock()` is called before `charge()`, but no `try/except` releases the reserved stock when `charge()` raises `PaymentError`.
  - *Expected outcome:* Assistant calls `get_change`, inspects live `checkout.py`, confirms the missing `release_stock()` failure handler, adds the release-on-failure handling, runs `pytest`, and calls `record_change` to log the fix referencing `R01`'s entry ID.
- **R05 (False Alarm — Already Validated Upstream):**
  - *Setup:* Record an entry whose review question asks *"Can `quantity` be zero or negative here?"*, where `validate_positive_quantity(quantity)` is already called on the first line of the function.
  - *Expected outcome:* Assistant calls `get_change`, reads live code, explains that `validate_positive_quantity` already guards the input, and makes **no code edit** and **no new log entry**.

#### Step 5B: Expanded Review Matrix (Expand After Starter Set Passes — up to 10 Cases)
- **Additional Seeded Bugs (R02–R04):**
  - **R02:** Empty-list division-by-zero in average rating helper.
  - **R03:** Unrelated comment added at top of `checkout.py` (`file_modified_excerpt_intact` with shifted lines) while the seeded bug in the excerpt remains broken; assistant uses updated line span, fixes the bug, and logs the fix.
  - **R04:** `except Exception: return True` fail-open bug in permission check.
- **Additional False Alarms (R06–R07):**
  - **R06:** Idempotent `close_session()` called twice safely.
  - **R07:** Correct `<=` boundary check on a 1-indexed retry counter.
- **Stale / Removed Code Cases (R08–R10):**
  - **R08 (`excerpt_modified_or_removed`):** Bug from `R01` was already fixed manually in the file before asking the assistant to review the old entry; assistant sees live code is fixed and makes **no edit**.
  - **R09 (`excerpt_modified_or_removed`):** Logged function was replaced by a different module structure; assistant reports code was replaced and makes **no edit**.
  - **R10 (`file_missing`):** Referenced source file was deleted; assistant reports `file_missing` and makes **no edit**.

**Done when (Phase 5 Gates across ≥3 runs per case):**
- Seeded bugs (`R01–R04`) confirmed, fixed, tested, and logged as a follow-up entry: **≥90%** pass rate.
- **No speculative code edits** on false alarms (`R05–R07`) or already-fixed/stale entries (`R08–R10`): **100%** required across all runs.

---

## Phase 6 — Second client, portability, concurrency, scale, and published results

**Goal:** Verify the second client, add automated stress/fuzz coverage, write `architecture.md` reflecting the settled code, and publish measured timings and evaluation rates in `README.md`.

### Work

1. **Second Client & Portability Verification:**
   - Install and smoke-test in the second supported client (Codex if Phase 3 used Claude Code, or Claude Code if Phase 3 used Codex).
   - Verify both project-scoped (`.claude/skills/code-story/`) and user-scoped (`~/.claude/skills/code-story/`) installs in Claude Code.
   - Verify path handling across platforms and record exact tested client and runtime versions in `README.md`.
2. **Concurrency, Scale & Fuzz Tests (`tests/test_phase6_hardening.py`):**
   - **Concurrent appends:** Spawn 8 worker processes appending 5 entries each (40 total) to the same `.ai-code-log.md`; verify all 40 entries parse cleanly with no interleaved text.
   - **Measured scale timings:** Generate logs of stated sizes (e.g., 100 and 250 entries), measure `record_change`, `list_changes`, and `get_change` latencies, and record the median/p95 timings along with the exact CPU/OS/disk specs of the test machine.
   - **Fuzzing:** Fuzz the parser and validator with arbitrary Unicode, nested backtick/tilde runs, and truncated trailing entries.
3. **Documentation Finalization:**
   - Write `architecture.md` describing the settled implementation.
   - Document the manual archive workflow (moving older entries to `.ai-code-log.archive.md`).
   - Update `README.md` with the verified features, exact client versions, measured timings on the named machine, and Phase 4–5 multi-run evaluation tables.

**Done when:** Both clients pass clean-room setup, `uv run pytest` passes the full Phase 1, 2, and 6 suites, and another engineer can reproduce the setup and published measurements from `README.md`.
