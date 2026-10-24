"""Session repository."""

from __future__ import annotations

import contextlib
import json
from datetime import UTC, datetime

import aiosqlite

from ...models import ResearchPlan, Session


def _now() -> str:
    return datetime.now(UTC).isoformat()


async def insert(conn: aiosqlite.Connection, s: Session) -> None:
    await conn.execute(
        """INSERT INTO sessions(
               id, created_at, updated_at, status, research_goal, research_plan,
               config_snapshot, budget_tokens, budget_usd, budget_used_tokens,
               budget_used_usd, wall_deadline, final_overview)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            s.id,
            s.created_at.isoformat(),
            s.updated_at.isoformat(),
            s.status,
            s.research_goal,
            s.research_plan.model_dump_json(),
            json.dumps(s.config_snapshot),
            s.budget_tokens,
            s.budget_usd,
            s.budget_used_tokens,
            s.budget_used_usd,
            s.wall_deadline.isoformat() if s.wall_deadline else None,
            s.final_overview,
        ),
    )
    await conn.commit()


async def fetch(conn: aiosqlite.Connection, session_id: str) -> Session | None:
    async with conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)) as cur:
        row = await cur.fetchone()
    if row is None:
        return None
    return _row_to_session(row)


async def fetch_row(conn: aiosqlite.Connection, session_id: str) -> dict | None:
    """Raw session row as a plain dict (stored strings untouched).

    Only `research_plan` and `config_snapshot` are JSON-decoded; if decoding
    fails the stored string is left as-is.
    """
    async with conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)) as cur:
        row = await cur.fetchone()
    if row is None:
        return None
    out = dict(row)
    for col in ("research_plan", "config_snapshot"):
        with contextlib.suppress(Exception):
            out[col] = json.loads(out[col])
    return out


async def set_status(conn: aiosqlite.Connection, session_id: str, status: str) -> None:
    await conn.execute(
        "UPDATE sessions SET status=?, updated_at=? WHERE id=?",
        (status, _now(), session_id),
    )
    await conn.commit()


async def add_usage(
    conn: aiosqlite.Connection, session_id: str, tokens: int, usd: float
) -> None:
    await conn.execute(
        """UPDATE sessions
              SET budget_used_tokens = budget_used_tokens + ?,
                  budget_used_usd    = budget_used_usd    + ?,
                  updated_at         = ?
            WHERE id = ?""",
        (tokens, usd, _now(), session_id),
    )
    await conn.commit()


async def set_final_overview(conn: aiosqlite.Connection, session_id: str, rel_path: str) -> None:
    await conn.execute(
        "UPDATE sessions SET final_overview=?, status='done', updated_at=? WHERE id=?",
        (rel_path, _now(), session_id),
    )
    await conn.commit()


async def list_with_stats(
    conn: aiosqlite.Connection, *, limit: int | None = None
) -> list[dict]:
    """Sessions newest-updated first, with hypothesis count and best Elo."""
    sql = """SELECT id, status, research_goal, created_at, updated_at,
                    budget_usd, budget_used_usd,
                    (SELECT COUNT(*) FROM hypotheses WHERE session_id = s.id) AS n_hyps,
                    (SELECT MAX(elo) FROM hypotheses WHERE session_id = s.id) AS top_elo
               FROM sessions s
               ORDER BY updated_at DESC"""
    args: tuple = ()
    if limit is not None:
        sql += " LIMIT ?"
        args = (limit,)
    async with conn.execute(sql, args) as cur:
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def ids_created_since(conn: aiosqlite.Connection, iso_ts: str) -> list[str]:
    async with conn.execute("SELECT id FROM sessions WHERE created_at >= ?", (iso_ts,)) as cur:
        return [r["id"] for r in await cur.fetchall()]


async def ids_for_goal(conn: aiosqlite.Connection, goal: str) -> list[str]:
    """Session ids with exactly this research goal, newest first."""
    async with conn.execute(
        "SELECT id FROM sessions WHERE research_goal = ? ORDER BY created_at DESC",
        (goal,),
    ) as cur:
        return [r["id"] for r in await cur.fetchall()]


async def set_research_plan(conn: aiosqlite.Connection, session_id: str, plan: dict) -> None:
    await conn.execute(
        "UPDATE sessions SET research_plan=?, updated_at=? WHERE id=?",
        (json.dumps(plan), _now(), session_id),
    )
    await conn.commit()


def _row_to_session(row: aiosqlite.Row) -> Session:
    return Session(
        id=row["id"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        status=row["status"],
        research_goal=row["research_goal"],
        research_plan=ResearchPlan.model_validate_json(row["research_plan"]),
        config_snapshot=json.loads(row["config_snapshot"]),
        budget_tokens=row["budget_tokens"],
        budget_usd=row["budget_usd"],
        budget_used_tokens=row["budget_used_tokens"],
        budget_used_usd=row["budget_used_usd"],
        wall_deadline=datetime.fromisoformat(row["wall_deadline"]) if row["wall_deadline"] else None,
        final_overview=row["final_overview"],
    )
