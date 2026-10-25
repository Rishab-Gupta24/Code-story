# CLAUDE.md

Code Story is a stdio MCP server (Python 3.11+, `uv`) that lets a coding assistant append focused, reviewable explanations of its changes to `<project_root>/.ai-code-log.md`.

## Layout

- `src/code_story/log.py`: validation, excerpt matching, secret scanning, fencing, locking (`record_change_entry`).
- `src/code_story/review.py`: fence-aware parser with recovery (`parse_log`), five-state drift, `list_change_entries` / `get_change_entry`.
- `src/code_story/server.py`: MCP tools `record_change`, `list_changes`, `get_change` (wraps errors as `{"ok": false, "error": <code>}`).
- `skills/code-story/SKILL.md`: assistant-facing instructions for when and how to log.
- `eval/fixture_app/`: Phase 4–5 fixture app (its own `pyproject.toml`; not part of this package's test run). `eval/tasks_bank.yaml` (Phase 4) and `eval/review_cases.yaml` (Phase 5): prompts plus answer keys; scored runs in `eval/results/`. `eval/phase5_regression_checks.py` runs the R01–R04 failure paths against run folders (the baseline suite covers only success paths). Run evaluations only in a copy outside this repo, so the answer key and this file never reach the assistant under test.
- `tests/test_phase1_log.py`, `tests/test_phase2_review.py`: Phase 1 and 2 suites. CI: `.github/workflows/tests.yml` (Python 3.11 and 3.14 on Ubuntu).

## Commands

- `uv sync`: install dependencies.
- `uv run pytest -v`: run tests.
- `uv run code-story`: start the server. If Windows Application Control blocks the `.exe` shim, use `uv run python -m code_story.server`.

## Project rules

- Build plan and phase gates live in `tasks.md`. Work one phase at a time; don't start the next deterministic phase until the current gate passes.
- `README.md` must only describe behavior that exists and passes tests. Never overclaim.
- Never report test results you didn't actually run. Paste real pytest output.
- Run `uv run pytest -v` after every change. Python 3.11+ is the minimum; don't use newer-only syntax.
- Don't add hooks, file watchers, or a second reviewer model before Phase 5.
- Log entries are append-only. Entry format is specified in `tasks.md`; don't change it without updating the spec.
- `test_reject_symlink_escape` skips on Windows without Developer Mode; Linux CI is where it actually runs, so check CI before trusting a local "skipped".
