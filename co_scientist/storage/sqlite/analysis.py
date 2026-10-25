"""Analysis report and per-candidate points repository (SQLite)."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import aiosqlite

from ..atlas._codec import aware, now

REPORT_FIELDS = (
    "summary_markdown", "tests", "methods", "candidates", "selection",
    "sample_count", "drugs", "plots", "survival_curves",
)


async def save_report(conn: aiosqlite.Connection, session_id: str, report: dict[str, Any]) -> None:
    doc = {k: report[k] for k in REPORT_FIELDS if k in report}
    await conn.execute(
        """INSERT INTO analysis_reports(session_id, doc, created_at) VALUES (?,?,?)
           ON CONFLICT(session_id) DO UPDATE SET doc=excluded.doc, created_at=excluded.created_at""",
        (session_id, json.dumps(doc), now().isoformat()),
    )
    await conn.commit()


async def fetch_report(conn: aiosqlite.Connection, session_id: str) -> dict[str, Any] | None:
    async with conn.execute(
        "SELECT doc, created_at FROM analysis_reports WHERE session_id=?", (session_id,)
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        return None
    return {**json.loads(row["doc"]), "created_at": aware(datetime.fromisoformat(row["created_at"]))}


async def save_points(
    conn: aiosqlite.Connection, session_id: str, candidate_key: str, *,
    metric: str, unit: str, points: list[dict[str, Any]],
) -> None:
    await conn.execute(
        """INSERT INTO analysis_points(session_id, candidate_key, metric, unit, points)
           VALUES (?,?,?,?,?)
           ON CONFLICT(session_id, candidate_key) DO UPDATE SET
               metric=excluded.metric, unit=excluded.unit, points=excluded.points""",
        (session_id, candidate_key, metric, unit, json.dumps(points)),
    )
    await conn.commit()


async def fetch_points(
    conn: aiosqlite.Connection, session_id: str, candidate_keys: list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if candidate_keys is None:
        async with conn.execute(
            """SELECT candidate_key, metric, unit, points FROM analysis_points
               WHERE session_id=?""",
            (session_id,),
        ) as cur:
            async for r in cur:
                out[r["candidate_key"]] = {
                    "metric": r["metric"], "unit": r["unit"], "points": json.loads(r["points"]),
                }
        return out
    if not candidate_keys:
        return {}
    keys = list(dict.fromkeys(candidate_keys))
    for i in range(0, len(keys), 500):  # stay under SQLite's variable limit
        chunk = keys[i : i + 500]
        marks = ",".join("?" * len(chunk))
        async with conn.execute(
            f"""SELECT candidate_key, metric, unit, points FROM analysis_points
                WHERE session_id=? AND candidate_key IN ({marks})""",
            (session_id, *chunk),
        ) as cur:
            async for r in cur:
                out[r["candidate_key"]] = {
                    "metric": r["metric"], "unit": r["unit"], "points": json.loads(r["points"]),
                }
    return out
