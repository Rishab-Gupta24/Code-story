"""stdio MCP server exposing record_change, list_changes and get_change."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from code_story.log import CodeStoryError, record_change_entry
from code_story.review import get_change_entry, list_change_entries

mcp = MCPServer("code-story")


def _error(exc: CodeStoryError) -> dict[str, object]:
    return {"ok": False, "error": exc.code, "message": str(exc)}


def record_change(
    project_root: str,
    summary: str,
    explanation: str,
    reason: str,
    files: list[str],
    code_excerpt: str,
    checks: str,
    review_question: str,
    code_language: str = "",
) -> dict[str, object]:
    """Append one Code Story entry to <project_root>/.ai-code-log.md.

    project_root is the absolute project path; files are paths relative to it.
    code_excerpt must be copied exactly from one of the listed files. checks
    must describe only checks that were actually run.
    """
    try:
        result = record_change_entry(
            project_root=project_root,
            summary=summary,
            explanation=explanation,
            reason=reason,
            files=files,
            code_excerpt=code_excerpt,
            checks=checks,
            review_question=review_question,
            code_language=code_language,
        )
    except CodeStoryError as exc:
        return _error(exc)
    return {
        "ok": True,
        "entry_id": result.entry_id,
        "log_path": result.log_path,
        "warnings": result.warnings,
    }


def list_changes(project_root: str, limit: int = 10) -> dict[str, object]:
    """List recent Code Story entry IDs and titles, newest first (limit 1-50).

    Damaged entries are still listed with malformed=true, and warnings explain
    what is wrong with them.
    """
    try:
        return {"ok": True, **list_change_entries(project_root, limit)}
    except CodeStoryError as exc:
        return _error(exc)


def get_change(project_root: str, entry_id: str) -> dict[str, object]:
    """Fetch one Code Story entry by ID (case-insensitive) with per-file drift.

    Each recorded file gets a drift state: unchanged, file_modified_excerpt_intact
    (with the excerpt's current line span), excerpt_modified_or_removed,
    file_modified_no_excerpt, or file_missing. Drift states show where to
    inspect the live code; they do not say whether a bug is present.
    """
    try:
        return {"ok": True, **get_change_entry(project_root, entry_id)}
    except CodeStoryError as exc:
        return _error(exc)


for _tool in (record_change, list_changes, get_change):
    mcp.add_tool(_tool)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
