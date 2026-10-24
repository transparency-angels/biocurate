"""Transcript repository — one row per LLM call."""

from __future__ import annotations

import aiosqlite

from ...models import Transcript


async def insert(conn: aiosqlite.Connection, t: Transcript) -> None:
    await conn.execute(
        """INSERT INTO transcripts(
               id, session_id, task_id, agent, action, model,
               input_tokens, output_tokens, cache_read, cache_write, cost_usd,
               started_at, finished_at, artifact_path)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            t.id, t.session_id, t.task_id, t.agent, t.action, t.model,
            t.input_tokens, t.output_tokens, t.cache_read, t.cache_write, t.cost_usd,
            t.started_at.isoformat(), t.finished_at.isoformat(), t.artifact_path,
        ),
    )
    await conn.commit()


async def usage_summary(conn: aiosqlite.Connection, session_id: str) -> dict[str, float | int]:
    async with conn.execute(
        """SELECT
               COALESCE(SUM(input_tokens),0)  AS input_tokens,
               COALESCE(SUM(output_tokens),0) AS output_tokens,
               COALESCE(SUM(cache_read),0)    AS cache_read,
               COALESCE(SUM(cache_write),0)   AS cache_write,
               COALESCE(SUM(cost_usd),0.0)    AS cost_usd,
               COUNT(*)                       AS n_calls
             FROM transcripts WHERE session_id=?""",
        (session_id,),
    ) as cur:
        row = await cur.fetchone()
    return dict(row) if row else {}


async def durations_ms(conn: aiosqlite.Connection, session_id: str) -> list[float]:
    """Per-call latency in ms, ascending (rough: whole-second resolution)."""
    async with conn.execute(
        """SELECT (strftime('%s', finished_at) - strftime('%s', started_at)) * 1000 AS dur_ms
              FROM transcripts WHERE session_id=? ORDER BY dur_ms""",
        (session_id,),
    ) as cur:
        return [r["dur_ms"] for r in await cur.fetchall() if r["dur_ms"] is not None]
