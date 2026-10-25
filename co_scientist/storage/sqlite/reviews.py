"""Review repository."""

from __future__ import annotations

import json
from datetime import datetime

import aiosqlite

from ...models import AssumptionCheck, Evidence, Review, ReviewScores


async def insert(conn: aiosqlite.Connection, r: Review) -> bool:
    cur = await conn.execute(
        """INSERT OR IGNORE INTO reviews(
               id, hypothesis_id, session_id, created_at, kind, verdict,
               novelty, correctness, testability, feasibility, body, artifact_path,
               evidence, assumptions)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
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
            json.dumps([e.model_dump(mode="json") for e in r.evidence]),
            json.dumps([a.model_dump(mode="json") for a in r.assumptions]),
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
        assumptions=[AssumptionCheck.model_validate(a) for a in _loads(row["assumptions"])],
        evidence=[Evidence.model_validate(e) for e in _loads(row["evidence"])],
        body=row["body"],
        artifact_path=row["artifact_path"],
    )


def _loads(raw: str | None) -> list:
    return json.loads(raw) if raw else []
