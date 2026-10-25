"""Timeline repository (SQLite)."""

from __future__ import annotations

import asyncio
import json
import weakref
from datetime import datetime

import aiosqlite

from ...models.timeline import TimelineMessage, TimelineRole
from ..atlas._codec import aware, now

# Serialises appends on one connection (BEGIN IMMEDIATE cannot nest); other
# connections are serialised by SQLite's write lock. Same pattern as tournaments.
_WRITE_LOCKS: weakref.WeakKeyDictionary[aiosqlite.Connection, asyncio.Lock] = (
    weakref.WeakKeyDictionary()
)


def _from_row(r) -> TimelineMessage:
    return TimelineMessage(
        session_id=r["session_id"],
        seq=r["seq"],
        ts=aware(datetime.fromisoformat(r["ts"])),
        role=r["role"],
        agent=r["agent"],
        kind=r["kind"],
        title=r["title"],
        body_markdown=r["body_markdown"],
        refs=json.loads(r["refs"]),
    )


async def append(
    conn: aiosqlite.Connection,
    session_id: str,
    *,
    role: TimelineRole,
    agent: str | None,
    kind: str,
    title: str,
    body_markdown: str,
    refs: list[str],
) -> TimelineMessage:
    """Insert with the next per-session `seq`, allocated atomically."""
    lock = _WRITE_LOCKS.get(conn)
    if lock is None:
        lock = _WRITE_LOCKS[conn] = asyncio.Lock()
    async with lock:
        ts = now()
        began = False
        try:
            await conn.execute("BEGIN IMMEDIATE")
            began = True
            async with conn.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 AS n FROM timeline WHERE session_id=?",
                (session_id,),
            ) as cur:
                row = await cur.fetchone()
            seq = int(row["n"])
            await conn.execute(
                """INSERT INTO timeline(
                       session_id, seq, ts, role, agent, kind, title, body_markdown, refs)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (session_id, seq, ts.isoformat(), role, agent, kind, title,
                 body_markdown, json.dumps(refs)),
            )
            await conn.commit()
        except BaseException:
            # A failed BEGIN leaves someone else's transaction open; don't roll it back.
            if began:
                await conn.rollback()
            raise
    return TimelineMessage(
        session_id=session_id, seq=seq, ts=ts, role=role, agent=agent,
        kind=kind, title=title, body_markdown=body_markdown, refs=list(refs),
    )


async def list_for_session(
    conn: aiosqlite.Connection, session_id: str, *, after_seq: int = 0, limit: int = 500
) -> list[TimelineMessage]:
    async with conn.execute(
        "SELECT * FROM timeline WHERE session_id=? AND seq>? ORDER BY seq LIMIT ?",
        (session_id, after_seq, limit),
    ) as cur:
        return [_from_row(r) async for r in cur]
