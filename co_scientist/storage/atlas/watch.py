"""Follow a session's timeline on Atlas through a change stream."""

from __future__ import annotations

from collections.abc import AsyncIterator

from ...models.timeline import TimelineMessage
from . import timeline as _timeline
from .client import AtlasConn

_PAGE = 500


async def timeline_after(
    conn: AtlasConn, session_id: str, after_seq: int
) -> AsyncIterator[TimelineMessage]:
    """Yield the backlog after `after_seq`, then every new insert, without repeats.

    The change stream is opened BEFORE the backlog is read, so an insert landing
    between the two is caught by the stream (and dropped there if the backlog
    already had it). Repeats are dropped by a set of yielded `seq`s rather than
    a high-water mark: two concurrent appends can commit out of `seq` order, and
    a mark would silently drop the lower one.
    """
    pipeline = [
        {"$match": {"operationType": "insert", "fullDocument.session_id": session_id}}
    ]
    seen: set[int] = set()
    async with await conn.coll(_timeline._COLL).watch(pipeline) as stream:
        last = after_seq
        while True:
            batch = await _timeline.list_for_session(
                conn, session_id, after_seq=last, limit=_PAGE
            )
            for m in batch:
                last = m.seq
                seen.add(m.seq)
                yield m
            if len(batch) < _PAGE:
                break
        async for change in stream:
            m = _timeline._from_doc(change["fullDocument"])
            if m.seq <= after_seq or m.seq in seen:
                continue
            seen.add(m.seq)
            yield m
