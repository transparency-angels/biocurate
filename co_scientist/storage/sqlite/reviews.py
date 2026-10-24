"""Review repository."""

from __future__ import annotations

from datetime import datetime

import aiosqlite

from ...models import Review, ReviewScores


async def insert(conn: aiosqlite.Connection, r: Review) -> bool:
    cur = await conn.execute(
        """INSERT OR IGNORE INTO reviews(
               id, hypothesis_id, session_id, created_at, kind, verdict,
               novelty, correctness, testability, feasibility, body, artifact_path)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            r.id,
            r.hypothesis_id,
            r.session_id,
            r.created_at.isoformat(),
            r.kind,
            r.verdict,
            r.scores.novelty,
            r.scores.correctness,
            r.scores.testability,
            r.scores.feasibility,
            r.body,
            r.artifact_path,
        ),
    )
    inserted = cur.rowcount > 0
    await conn.commit()
    return inserted


async def fetch(conn: aiosqlite.Connection, review_id: str) -> Review | None:
    async with conn.execute("SELECT * FROM reviews WHERE id = ?", (review_id,)) as cur:
        row = await cur.fetchone()
    return _row_to_review(row) if row else None


async def list_for_hypothesis(conn: aiosqlite.Connection, hypothesis_id: str) -> list[Review]:
    async with conn.execute(
        "SELECT * FROM reviews WHERE hypothesis_id=? ORDER BY created_at DESC",
        (hypothesis_id,),
    ) as cur:
        rows = await cur.fetchall()
    return [_row_to_review(r) for r in rows]


async def list_for_session(conn: aiosqlite.Connection, session_id: str) -> list[Review]:
    async with conn.execute(
        "SELECT * FROM reviews WHERE session_id=? ORDER BY created_at DESC",
        (session_id,),
    ) as cur:
        rows = await cur.fetchall()
    return [_row_to_review(r) for r in rows]


def _row_to_review(row: aiosqlite.Row) -> Review:
    return Review(
        id=row["id"],
        hypothesis_id=row["hypothesis_id"],
        session_id=row["session_id"],
        created_at=datetime.fromisoformat(row["created_at"]),
        kind=row["kind"],
        verdict=row["verdict"],
        scores=ReviewScores(
            novelty=row["novelty"],
            correctness=row["correctness"],
            testability=row["testability"],
            feasibility=row["feasibility"],
        ),
        assumptions=[],   # in JSON artifact
        evidence=[],      # in JSON artifact
        body=row["body"],
        artifact_path=row["artifact_path"],
    )
