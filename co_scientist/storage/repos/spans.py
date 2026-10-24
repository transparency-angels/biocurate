"""Backend-dispatching `spans` repository."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from .. import Conn
from ..atlas import spans as _atlas
from ..sqlite import spans as _sql
from ._dispatch import dual

start = dual(_sql.start, _atlas.start)
end = dual(_sql.end, _atlas.end)


@asynccontextmanager
async def span(
    conn: Conn,
    *,
    trace_id: str,
    parent_span_id: str | None,
    session_id: str | None,
    task_id: str | None,
    name: str,
    attrs: dict[str, Any] | None = None,
) -> AsyncIterator[str]:
    """Open a span; ends it ok on exit, or with status=error if the body raises."""
    sid = await start(
        conn,
        trace_id=trace_id,
        parent_span_id=parent_span_id,
        session_id=session_id,
        task_id=task_id,
        name=name,
        attrs=attrs,
    )
    try:
        yield sid
        await end(conn, sid, status="ok")
    except Exception as exc:
        await end(conn, sid, status="error", attrs={"error": str(exc)})
        raise
