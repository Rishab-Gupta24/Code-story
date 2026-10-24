# CLAUDE.md

Code Story is a stdio MCP server (Python 3.11+, `uv`) that lets a coding assistant append focused, reviewable explanations of its changes to `<project_root>/.ai-code-log.md`.

## Layout

- `src/code_story/log.py`: validation, excerpt matching, secret scanning, fencing, locking (`record_change_entry`), plus basic `list_change_entries` / `get_change_entry`.
- `src/code_story/server.py`: MCP tools `record_change`, `list_changes`, `get_change` (wraps errors as `{"ok": false, "error": <code>}`).
- `skills/code-story/SKILL.md`: assistant-facing instructions for when and how to log.
- `tests/test_phase1_log.py`: Phase 1 suite. CI: `.github/workflows/tests.yml` (Python 3.11 and 3.14 on Ubuntu).

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
- `test_reject_symlink_escape` skips on Windows without Developer Mode; it must pass in Linux CI before the Phase 1 gate closes.
