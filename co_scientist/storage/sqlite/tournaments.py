"""Tournament matches + Elo journal.

The Elo update is the *only* place hypotheses.elo and matches_played mutate
during a session. `record_match_result` reads the current ratings, computes the update and
writes it in a single BEGIN IMMEDIATE transaction guarded by elo_journal.match_id UNIQUE —
so concurrent matches never lose an update and re-running the same match is a no-op.
"""

from __future__ import annotations

import asyncio
import time
import weakref
from datetime import datetime

import aiosqlite

from ...models import TournamentMatch
from ...orchestrator.elo import AppliedElo, update_elo


async def insert_match(conn: aiosqlite.Connection, m: TournamentMatch) -> bool:
    """Insert the descriptive match row. Idempotent by id."""
    cur = await conn.execute(
        """INSERT OR IGNORE INTO tournament_matches(
               id, session_id, created_at, hyp_a, hyp_b, mode, winner,
               elo_a_before, elo_b_before, elo_a_after, elo_b_after,
               rationale, transcript_id, similarity)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            m.id, m.session_id, m.created_at.isoformat(),
            m.hyp_a, m.hyp_b, m.mode, m.winner,
            m.elo_a_before, m.elo_b_before, m.elo_a_after, m.elo_b_after,
            m.rationale, m.transcript_id, m.similarity,
        ),
    )
    ok = cur.rowcount > 0
    await conn.commit()
    return ok


# Serialises record_match_result calls on one connection (BEGIN IMMEDIATE cannot nest).
# It does NOT isolate them from other writers sharing the connection: those use implicit
# transactions without this lock and can still interleave with, or join, our transaction.
# That predates this function. Other connections are serialized by SQLite's write lock.
_WRITE_LOCKS: weakref.WeakKeyDictionary[aiosqlite.Connection, asyncio.Lock] = (
    weakref.WeakKeyDictionary()
)


async def record_match_result(
    conn: aiosqlite.Connection,
    *,
    match_id: str,
    hyp_a: str,
    hyp_b: str,
    winner: str,
    k_new: int,
    k_warm: int,
    initial_elo: float,
) -> AppliedElo | None:
    """Compute and apply an Elo update from the *current* stored ratings, atomically.

    The reads happen after BEGIN IMMEDIATE, so a concurrent writer cannot slip a match
    in between the read and the write. Returns None if the journal already has this
    match_id (re-run; nothing written). Raises ValueError if a hypothesis is missing.
    """
    lock = _WRITE_LOCKS.get(conn)
    if lock is None:
        lock = _WRITE_LOCKS[conn] = asyncio.Lock()
    async with lock:
        applied_at = int(time.time() * 1000)
        began = False
        try:
            await conn.execute("BEGIN IMMEDIATE")
            began = True
            cur_elo: dict[str, tuple[float, int]] = {}
            for hid in (hyp_a, hyp_b):
                async with conn.execute(
                    "SELECT elo, matches_played FROM hypotheses WHERE id=?", (hid,)
                ) as cur:
                    row = await cur.fetchone()
                if row is None:
                    raise ValueError(f"no such hypothesis: {hid}")
                elo = row["elo"]
                cur_elo[hid] = (initial_elo if elo is None else float(elo), row["matches_played"])
            (elo_a, mp_a), (elo_b, mp_b) = cur_elo[hyp_a], cur_elo[hyp_b]
            upd = update_elo(elo_a, elo_b, winner, min(mp_a, mp_b), k_new=k_new, k_warm=k_warm)
            await conn.execute(
                """INSERT INTO elo_journal(
                       update_id, match_id, hyp_a, hyp_b, winner,
                       elo_a_before, elo_b_before, elo_a_after, elo_b_after, applied_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (match_id, match_id, hyp_a, hyp_b, winner,
                 elo_a, elo_b, upd.elo_a_after, upd.elo_b_after, applied_at),
            )
            for hid, elo_after in ((hyp_a, upd.elo_a_after), (hyp_b, upd.elo_b_after)):
                await conn.execute(
                    "UPDATE hypotheses SET elo=?, matches_played=matches_played+1 WHERE id=?",
                    (elo_after, hid),
                )
            # reflect the in-transaction values into the descriptive match row
            await conn.execute(
                """UPDATE tournament_matches
                      SET elo_a_before=?, elo_b_before=?, elo_a_after=?, elo_b_after=?
                    WHERE id=?""",
                (elo_a, elo_b, upd.elo_a_after, upd.elo_b_after, match_id),
            )
            await conn.commit()
        except aiosqlite.IntegrityError:
            # match_id already in journal — idempotent skip.
            if began:
                await conn.rollback()
            return None
        except BaseException:
            # A failed BEGIN leaves someone else's transaction open; don't roll it back.
            if began:
                await conn.rollback()
            raise
    return AppliedElo(
        elo_a_before=elo_a, elo_b_before=elo_b,
        elo_a_after=upd.elo_a_after, elo_b_after=upd.elo_b_after,
        k=upd.k, expected_a=upd.expected_a,
    )


async def count_matches(conn: aiosqlite.Connection, session_id: str) -> int:
    async with conn.execute(
        "SELECT COUNT(*) AS n FROM tournament_matches WHERE session_id=? AND mode != 'invalid'",
        (session_id,),
    ) as cur:
        row = await cur.fetchone()
    return row["n"] if row else 0


async def recent_rationales(
    conn: aiosqlite.Connection, session_id: str, limit: int = 50
) -> list[str]:
    async with conn.execute(
        """SELECT rationale FROM tournament_matches
              WHERE session_id=? AND rationale IS NOT NULL
              ORDER BY created_at DESC LIMIT ?""",
        (session_id, limit),
    ) as cur:
        rows = await cur.fetchall()
    return [r["rationale"] for r in rows]


async def list_for_session(
    conn: aiosqlite.Connection, session_id: str, *, limit: int
) -> list[TournamentMatch]:
    """Most recent matches first."""
    async with conn.execute(
        """SELECT * FROM tournament_matches
             WHERE session_id=?
             ORDER BY created_at DESC LIMIT ?""",
        (session_id, limit),
    ) as cur:
        rows = await cur.fetchall()
    return [_row_to_match(r) for r in rows]


async def list_for_hypothesis(
    conn: aiosqlite.Connection, hypothesis_id: str
) -> list[TournamentMatch]:
    """Every match the hypothesis played, oldest first."""
    async with conn.execute(
        """SELECT * FROM tournament_matches
            WHERE hyp_a=? OR hyp_b=?
            ORDER BY created_at""",
        (hypothesis_id, hypothesis_id),
    ) as cur:
        rows = await cur.fetchall()
    return [_row_to_match(r) for r in rows]


async def count_by_mode(conn: aiosqlite.Connection, session_id: str) -> dict[str, int]:
    async with conn.execute(
        "SELECT mode AS k, COUNT(*) AS n FROM tournament_matches WHERE session_id=? GROUP BY mode",
        (session_id,),
    ) as cur:
        return {r["k"]: r["n"] for r in await cur.fetchall()}


def _row_to_match(row: aiosqlite.Row) -> TournamentMatch:
    return TournamentMatch(
        id=row["id"],
        session_id=row["session_id"],
        created_at=datetime.fromisoformat(row["created_at"]),
        hyp_a=row["hyp_a"], hyp_b=row["hyp_b"], mode=row["mode"],
        winner=row["winner"],
        elo_a_before=row["elo_a_before"], elo_b_before=row["elo_b_before"],
        elo_a_after=row["elo_a_after"], elo_b_after=row["elo_b_after"],
        rationale=row["rationale"], transcript_id=row["transcript_id"],
        similarity=row["similarity"],
    )
