---
name: code-story
description: Log a focused, plain-language explanation of each meaningful completed code change to .ai-code-log.md with the Code Story MCP tools, and review logged entries by ID. Use after finishing a behavior change, new logic, bug fix, data-flow change or non-obvious refactor, or when asked to review a Code Story entry (CS-...).
---

# Code Story

Code Story keeps a reviewable log of meaningful changes in `<project_root>/.ai-code-log.md`, written through the `code-story` MCP server.

## When to log

Call `record_change` once per coherent, **completed** change that alters behavior:

- bug fixes, new logic, validation guards, important data-flow changes, non-obvious refactors

Do **not** log:

- formatting, import sorting, comments or docstrings only, generated files, lockfile or dependency churn, trivial renames
- unfinished work: stubs, code that does not run yet, exploration you reverted, or a change paused on a question to the user

## How to log

- `project_root`: absolute path of the project being edited.
- `files`: paths relative to `project_root`. Put the file that contains the excerpt first.
- `code_excerpt`: copy the changed logic **exactly** from the file on disk (at most 100 lines / 4,000 characters). The server rejects excerpts that are not in a listed file. Never include credentials, tokens or private data.
- `summary`: one line. `explanation`: what the code does now. `reason`: why it changed.
- `checks`: only checks you actually ran and their results. If you ran nothing, or only part (for example only the happy path), say so plainly. Never claim a test passed that you did not run.
- `review_question`: one concrete risk or assumption a reviewer should check.

If the response includes `warnings` about a possible credential, redact the value and record again. If it returns `LOCK_TIMEOUT`, nothing was written; retry once.

## Reviewing an entry

When asked to review entry `CS-...`:

1. Call `get_change` and read any drift warnings.
2. Read the live source on disk; the log is history, not the current code.
3. Confirm the suspected issue actually exists before editing. If it does not (false alarm, already fixed, code replaced or file removed), explain why and make no edit and no new entry.
4. If you fix a confirmed issue, run the relevant checks, then call `record_change` for the fix and mention the original entry ID in `reason`.

Use `list_changes` to find recent entry IDs.
