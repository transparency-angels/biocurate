"""Atlas implementations for `spans` (stubs; filled in Tasks 4 and 5)."""

from __future__ import annotations

from typing import Any

from .client import AtlasConn


async def start(
    conn: AtlasConn,
    *,
    trace_id: str,
    parent_span_id: str | None,
    session_id: str | None,
    task_id: str | None,
    name: str,
    attrs: dict[str, Any] | None = None,
) -> str:
    raise NotImplementedError("spans.start on Atlas: Task 4/5")


async def end(
    conn: AtlasConn,
    span_id_: str,
    *,
    status: str = "ok",
    attrs: dict[str, Any] | None = None,
) -> None:
    raise NotImplementedError("spans.end on Atlas: Task 4/5")
