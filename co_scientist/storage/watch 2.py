"""Live-follow a session's timeline on either backend.

Not a `dual()` repo: `dual` awaits a coroutine, and this is an async generator,
so it branches on the connection type itself. Atlas uses a change stream (so
inserts made by other processes show up); SQLite polls.

Close it with `contextlib.aclosing` so the change stream / poll loop stops
when the consumer does.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from typing import Any

from ..models.timeline import TimelineMessage
from .atlas import watch as _atlas
from .atlas.client import AtlasConn
from .sqlite import watch as _sql


async def timeline_after(
    conn: Any, session_id: str, after_seq: int
) -> AsyncIterator[TimelineMessage]:
    """Messages with `seq > after_seq`: the backlog, then new ones as they land."""
    inner = (
        _atlas.timeline_after(conn, session_id, after_seq)
        if isinstance(conn, AtlasConn)
        else _sql.timeline_after(conn, session_id, after_seq)
    )
    async with contextlib.aclosing(inner) as gen:
        async for m in gen:
            yield m
