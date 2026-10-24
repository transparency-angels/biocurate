"""Atlas implementations for `hypotheses`."""

from __future__ import annotations

from typing import Any

from pymongo.errors import DuplicateKeyError

from ...models import CitedPaper, Hypothesis
from ._codec import aware
from .client import AtlasConn

_COLL = "hypotheses"
_POOL = ["in_tournament", "pinned"]


def _to_doc(h: Hypothesis) -> dict[str, Any]:
    return {
        "_id": h.id,
        "session_id": h.session_id,
        "created_at": h.created_at,
        "created_by": h.created_by,
        "strategy": h.strategy,
        "parent_ids": list(h.parent_ids),
        "title": h.title,
        "summary": h.summary,
        "full_text": h.full_text,
        "artifact_path": h.artifact_path,
        "elo": h.elo,
        "matches_played": h.matches_played,
        "state": h.state,
        "dedup_cluster": h.dedup_cluster,
        "citations": [c.model_dump(mode="json") for c in h.citations],
        "data_evidence": h.data_evidence,
    }


def _from_doc(d: dict[str, Any]) -> Hypothesis:
    return Hypothesis(
        id=d["_id"],
        session_id=d["session_id"],
        created_at=aware(d["created_at"]),
        created_by=d["created_by"],
        strategy=d["strategy"],
        parent_ids=d.get("parent_ids") or [],
        title=d["title"],
        summary=d["summary"],
        full_text=d["full_text"],
        citations=[CitedPaper.model_validate(c) for c in d.get("citations") or []],
        artifact_path=d["artifact_path"],
        elo=d.get("elo"),
        matches_played=d["matches_played"],
        state=d["state"],
        dedup_cluster=d.get("dedup_cluster"),
        data_evidence=d.get("data_evidence"),
    )


async def insert(conn: AtlasConn, h: Hypothesis) -> bool:
    """Insert; returns True if a new row was created, False if it already existed."""
    try:
        await conn.coll(_COLL).insert_one(_to_doc(h))
    except DuplicateKeyError:
        return False
    return True


async def fetch(conn: AtlasConn, hypothesis_id: str) -> Hypothesis | None:
    d = await conn.coll(_COLL).find_one({"_id": hypothesis_id})
    return _from_doc(d) if d else None


async def fetch_many(conn: AtlasConn, ids: list[str]) -> list[Hypothesis]:
    if not ids:
        return []
    cur = conn.coll(_COLL).find({"_id": {"$in": list(ids)}})
    return [_from_doc(d) async for d in cur]


async def list_for_session(
    conn: AtlasConn, session_id: str, state: str | None = None
) -> list[Hypothesis]:
    if state:
        flt = {"session_id": session_id, "state": state}
        sort = [("elo", -1), ("_id", 1)]
    else:
        # Descending sorts put nulls last, like SQL `NULLS LAST`.
        flt = {"session_id": session_id}
        sort = [("elo", -1), ("created_at", 1), ("_id", 1)]
    cur = conn.coll(_COLL).find(flt).sort(sort)
    return [_from_doc(d) async for d in cur]


async def top_by_elo(conn: AtlasConn, session_id: str, k: int = 10) -> list[Hypothesis]:
    if k <= 0:  # Mongo reads limit(0) as "no limit"; SQL LIMIT 0 returns nothing
        return []
    cur = (
        conn.coll(_COLL)
        .find({"session_id": session_id, "state": {"$in": _POOL}})
        .sort([("elo", -1), ("_id", 1)])
        .limit(k)
    )
    return [_from_doc(d) async for d in cur]


async def count_by_state(conn: AtlasConn, session_id: str) -> dict[str, int]:
    cur = await conn.coll(_COLL).aggregate(
        [
            {"$match": {"session_id": session_id}},
            {"$group": {"_id": "$state", "n": {"$sum": 1}}},
        ]
    )
    return {d["_id"]: d["n"] async for d in cur}


async def elo_range(conn: AtlasConn, session_id: str) -> tuple[float | None, float | None, int]:
    """(min elo, max elo, number of hypotheses with an elo)."""
    cur = await conn.coll(_COLL).aggregate(
        [
            {"$match": {"session_id": session_id, "elo": {"$ne": None}}},
            {
                "$group": {
                    "_id": None,
                    "lo": {"$min": "$elo"},
                    "hi": {"$max": "$elo"},
                    "n": {"$sum": 1},
                }
            },
        ]
    )
    rows = await cur.to_list()
    if not rows:
        return (None, None, 0)
    return (rows[0]["lo"], rows[0]["hi"], rows[0]["n"])


async def top_elo_ids(conn: AtlasConn, session_id: str, k: int) -> list[tuple[str, float]]:
    if k <= 0:
        return []
    cur = (
        conn.coll(_COLL)
        .find(
            {"session_id": session_id, "state": {"$in": _POOL}, "elo": {"$ne": None}},
            {"elo": 1},
        )
        .sort([("elo", -1), ("_id", 1)])
        .limit(k)
    )
    return [(d["_id"], d["elo"]) async for d in cur]


async def pool_size(conn: AtlasConn, session_id: str) -> int:
    return await conn.coll(_COLL).count_documents(
        {"session_id": session_id, "state": {"$in": _POOL}}
    )


async def set_state(conn: AtlasConn, hypothesis_id: str, state: str) -> None:
    await conn.coll(_COLL).update_one({"_id": hypothesis_id}, {"$set": {"state": state}})


async def set_state_if(
    conn: AtlasConn,
    hypothesis_id: str,
    *,
    new_state: str,
    expected_states: tuple[str, ...],
) -> bool:
    """Conditional state transition. Returns True if applied."""
    res = await conn.coll(_COLL).update_one(
        {"_id": hypothesis_id, "state": {"$in": list(expected_states)}},
        {"$set": {"state": new_state}},
    )
    # matched, not modified: SQLite's rowcount counts a same-state rewrite as applied.
    return res.matched_count > 0


async def init_tournament(conn: AtlasConn, hypothesis_id: str, initial_elo: float = 1200.0) -> bool:
    """Set Elo and state if not already in tournament; returns True if applied."""
    res = await conn.coll(_COLL).update_one(
        {"_id": hypothesis_id, "elo": None},  # null or missing
        {"$set": {"elo": initial_elo, "state": "in_tournament"}},
    )
    return res.matched_count > 0


async def set_dedup_cluster(conn: AtlasConn, hypothesis_id: str, cluster: str | None) -> None:
    await conn.coll(_COLL).update_one(
        {"_id": hypothesis_id}, {"$set": {"dedup_cluster": cluster}}
    )
