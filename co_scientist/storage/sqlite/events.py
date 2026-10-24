"""Event log repository — structured event stream mirror of stdout JSONL."""

from __future__ import annotations

import json
import time
from typing import Any

import aiosqlite


async def emit(
    conn: aiosqlite.Connection,
    *,
    session_id: str | None,
    task_id: str | None,
    agent: str | None,
    event: str,
    payload: dict[str, Any] | None = None,
) -> None:
    await conn.execute(
        """INSERT INTO events(ts, session_id, task_id, agent, event, payload)
           VALUES (?,?,?,?,?,?)""",
        (
            int(time.time() * 1000),
            session_id,
            task_id,
            agent,
            event,
            json.dumps(payload) if payload else None,
        ),
    )
    await conn.commit()


async def recent(
    conn: aiosqlite.Connection, session_id: str, *, limit: int = 100
) -> list[dict[str, Any]]:
    async with conn.execute(
        """SELECT ts, session_id, task_id, agent, event, payload
             FROM events WHERE session_id=?
            ORDER BY ts DESC LIMIT ?""",
        (session_id, limit),
    ) as cur:
        rows = await cur.fetchall()
    out = []
    for r in rows:
        out.append(
            {
                "ts": r["ts"],
                "session_id": r["session_id"],
                "task_id": r["task_id"],
                "agent": r["agent"],
                "event": r["event"],
                "payload": json.loads(r["payload"]) if r["payload"] else None,
            }
        )
    return out


async def tool_call_counts(conn: aiosqlite.Connection, session_id: str) -> tuple[int, int]:
    """(tool_call events, those whose payload has is_error true)."""
    async with conn.execute(
        """SELECT
              SUM(CASE WHEN event='tool_call' THEN 1 ELSE 0 END) AS tools_called,
              SUM(CASE WHEN event='tool_call' AND payload LIKE '%"is_error": true%' THEN 1 ELSE 0 END) AS tool_errors
           FROM events WHERE session_id=?""",
        (session_id,),
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        return (0, 0)
    return (row["tools_called"] or 0, row["tool_errors"] or 0)
