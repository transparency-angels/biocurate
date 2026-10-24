"""Atlas implementations for `events` (stubs; filled in Tasks 4 and 5)."""

from __future__ import annotations

from typing import Any

from .client import AtlasConn


async def emit(
    conn: AtlasConn,
    *,
    session_id: str | None,
    task_id: str | None,
    agent: str | None,
    event: str,
    payload: dict[str, Any] | None = None,
) -> None:
    raise NotImplementedError("events.emit on Atlas: Task 4/5")


async def recent(conn: AtlasConn, session_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
    raise NotImplementedError("events.recent on Atlas: Task 4/5")


async def tool_call_counts(conn: AtlasConn, session_id: str) -> tuple[int, int]:
    """(tool_call events, those whose payload has is_error true)."""
    raise NotImplementedError("events.tool_call_counts on Atlas: Task 4/5")
