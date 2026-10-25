"""Final synthesis repository (SQLite)."""

from __future__ import annotations

import json
from typing import Any

import aiosqlite

from ..atlas._codec import now


async def save(conn: aiosqlite.Connection, session_id: str, doc: dict[str, Any]) -> None:
    await conn.execute(
        """INSERT INTO syntheses(session_id, doc, created_at) VALUES (?,?,?)
           ON CONFLICT(session_id) DO UPDATE SET doc=excluded.doc, created_at=excluded.created_at""",
        (session_id, json.dumps(doc), now().isoformat()),
    )
    await conn.commit()


async def fetch(conn: aiosqlite.Connection, session_id: str) -> dict[str, Any] | None:
    async with conn.execute("SELECT doc FROM syntheses WHERE session_id=?", (session_id,)) as cur:
        row = await cur.fetchone()
    return None if row is None else json.loads(row["doc"])
