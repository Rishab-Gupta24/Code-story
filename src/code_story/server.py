"""stdio MCP server exposing record_change, list_changes and get_change."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from code_story.log import (
    CodeStoryError,
    get_change_entry,
    list_change_entries,
    record_change_entry,
)

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
    """List recent Code Story entry IDs and titles, newest first (limit 1-50)."""
    try:
        return {"ok": True, "entries": list_change_entries(project_root, limit)}
    except CodeStoryError as exc:
        return _error(exc)


def get_change(project_root: str, entry_id: str) -> dict[str, object]:
    """Fetch one Code Story entry, warning if a recorded file changed or is missing."""
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
