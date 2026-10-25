"""Follow a session's timeline on SQLite by polling (no change streams here)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import aiosqlite

from ...models.timeline import TimelineMessage
from . import timeline as _timeline

# Read at each sleep, so tests can monkeypatch it smaller.
POLL_INTERVAL_S = 1.0
_PAGE = 500


async def timeline_after(
    conn: aiosqlite.Connection, session_id: str, after_seq: int
) -> AsyncIterator[TimelineMessage]:
    """Yield messages with `seq > after_seq`, then poll for new ones forever.

    SQLite `seq` is gap-free and allocated under the write lock, so a high-water
    mark is enough to never repeat or skip a message.
    """
    last = after_seq
    while True:
        batch = await _timeline.list_for_session(
            conn, session_id, after_seq=last, limit=_PAGE
        )
        for m in batch:
            last = m.seq
            yield m
        if len(batch) < _PAGE:
            await asyncio.sleep(POLL_INTERVAL_S)
