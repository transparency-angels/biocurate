"""Atlas implementations for `transcripts`."""

from __future__ import annotations

from typing import Any

from ...models import Transcript
from ._codec import aware
from .client import AtlasConn

_COLL = "transcripts"


def _to_doc(t: Transcript) -> dict[str, Any]:
    return {
        "_id": t.id,
        "session_id": t.session_id,
        "task_id": t.task_id,
        "agent": t.agent,
        "action": t.action,
        "model": t.model,
        "input_tokens": t.input_tokens,
        "output_tokens": t.output_tokens,
        "cache_read": t.cache_read,
        "cache_write": t.cache_write,
        "cost_usd": t.cost_usd,
        "started_at": t.started_at,
        "finished_at": t.finished_at,
        "artifact_path": t.artifact_path,
    }


def _from_doc(d: dict[str, Any]) -> Transcript:
    return Transcript(
        id=d["_id"],
        session_id=d["session_id"],
        task_id=d.get("task_id"),
        agent=d["agent"],
        action=d["action"],
        model=d["model"],
        input_tokens=d["input_tokens"],
        output_tokens=d["output_tokens"],
        cache_read=d["cache_read"],
        cache_write=d["cache_write"],
        cost_usd=d["cost_usd"],
        started_at=aware(d["started_at"]),
        finished_at=aware(d["finished_at"]),
        artifact_path=d["artifact_path"],
    )


async def insert(conn: AtlasConn, t: Transcript) -> None:
    await conn.coll(_COLL).insert_one(_to_doc(t))


async def usage_summary(conn: AtlasConn, session_id: str) -> dict[str, float | int]:
    cur = await conn.coll(_COLL).aggregate(
        [
            {"$match": {"session_id": session_id}},
            {
                "$group": {
                    "_id": None,
                    "input_tokens": {"$sum": "$input_tokens"},
                    "output_tokens": {"$sum": "$output_tokens"},
                    "cache_read": {"$sum": "$cache_read"},
                    "cache_write": {"$sum": "$cache_write"},
                    "cost_usd": {"$sum": "$cost_usd"},
                    "n_calls": {"$sum": 1},
                }
            },
        ]
    )
    rows = await cur.to_list()
    if not rows:  # SQL aggregates always yield a row
        return {
            "input_tokens": 0, "output_tokens": 0, "cache_read": 0, "cache_write": 0,
            "cost_usd": 0.0, "n_calls": 0,
        }
    r = rows[0]
    return {
        "input_tokens": r["input_tokens"],
        "output_tokens": r["output_tokens"],
        "cache_read": r["cache_read"],
        "cache_write": r["cache_write"],
        "cost_usd": float(r["cost_usd"]),
        "n_calls": r["n_calls"],
    }


async def durations_ms(conn: AtlasConn, session_id: str) -> list[float]:
    """Per-call latency in ms, ascending (rough: whole-second resolution).

    `$dateDiff` with unit `second` counts second boundaries crossed, i.e. the
    difference of the truncated timestamps, exactly what SQLite's
    `strftime('%s')` subtraction yields.
    """
    cur = await conn.coll(_COLL).aggregate(
        [
            {"$match": {"session_id": session_id}},
            {
                "$project": {
                    "dur_ms": {
                        "$multiply": [
                            {
                                "$dateDiff": {
                                    "startDate": "$started_at",
                                    "endDate": "$finished_at",
                                    "unit": "second",
                                }
                            },
                            1000,
                        ]
                    }
                }
            },
            {"$sort": {"dur_ms": 1}},
        ]
    )
    return [d["dur_ms"] async for d in cur if d.get("dur_ms") is not None]
