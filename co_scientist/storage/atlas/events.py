"""Atlas implementations for `events` (ObjectId `_id`, ordered by `ts`)."""

from __future__ import annotations

import time
from typing import Any

from .client import AtlasConn

_COLL = "events"


async def emit(
    conn: AtlasConn,
    *,
    session_id: str | None,
    task_id: str | None,
    agent: str | None,
    event: str,
    payload: dict[str, Any] | None = None,
) -> None:
    await conn.coll(_COLL).insert_one(
        {
            "ts": int(time.time() * 1000),
            "session_id": session_id,
            "task_id": task_id,
            "agent": agent,
            "event": event,
            "payload": payload or None,  # empty payload is stored as null, as in SQLite
        }
    )


async def recent(conn: AtlasConn, session_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
    if limit <= 0:  # Mongo reads limit(0) as "no limit"
        return []
    cur = (
        conn.coll(_COLL)
        .find({"session_id": session_id})
        .sort([("ts", -1), ("_id", -1)])
        .limit(limit)
    )
    return [
        {
            "ts": d["ts"],
            "session_id": d.get("session_id"),
            "task_id": d.get("task_id"),
            "agent": d.get("agent"),
            "event": d["event"],
            "payload": d.get("payload"),
        }
        async for d in cur
    ]


async def tool_call_counts(conn: AtlasConn, session_id: str) -> tuple[int, int]:
    """(tool_call events, those whose payload has is_error true)."""
    cur = await conn.coll(_COLL).aggregate(
        [
            {"$match": {"session_id": session_id, "event": "tool_call"}},
            {
                "$group": {
                    "_id": None,
                    "called": {"$sum": 1},
                    "errors": {
                        "$sum": {"$cond": [{"$eq": ["$payload.is_error", True]}, 1, 0]}
                    },
                }
            },
        ]
    )
    rows = await cur.to_list()
    return (rows[0]["called"], rows[0]["errors"]) if rows else (0, 0)
