"""Atlas implementations for `tournaments`.

`apply_elo_update` runs in a multi-document transaction guarded by the `_id` of the
`elo_journal` document (= match id), so re-applying the same match is a no-op.
"""

from __future__ import annotations

import time
from typing import Any

from pymongo.errors import DuplicateKeyError

from ...models import TournamentMatch
from ._codec import aware
from .client import AtlasConn

_COLL = "tournament_matches"


def _to_doc(m: TournamentMatch) -> dict[str, Any]:
    return {
        "_id": m.id,
        "session_id": m.session_id,
        "created_at": m.created_at,
        "hyp_a": m.hyp_a,
        "hyp_b": m.hyp_b,
        "mode": m.mode,
        "winner": m.winner,
        "elo_a_before": m.elo_a_before,
        "elo_b_before": m.elo_b_before,
        "elo_a_after": m.elo_a_after,
        "elo_b_after": m.elo_b_after,
        "rationale": m.rationale,
        "transcript_id": m.transcript_id,
        "similarity": m.similarity,
    }


def _from_doc(d: dict[str, Any]) -> TournamentMatch:
    return TournamentMatch(
        id=d["_id"],
        session_id=d["session_id"],
        created_at=aware(d["created_at"]),
        hyp_a=d["hyp_a"],
        hyp_b=d["hyp_b"],
        mode=d["mode"],
        winner=d.get("winner"),
        elo_a_before=d["elo_a_before"],
        elo_b_before=d["elo_b_before"],
        elo_a_after=d.get("elo_a_after"),
        elo_b_after=d.get("elo_b_after"),
        rationale=d.get("rationale"),
        transcript_id=d.get("transcript_id"),
        similarity=d.get("similarity"),
    )


async def insert_match(conn: AtlasConn, m: TournamentMatch) -> bool:
    """Insert the descriptive match row. Idempotent by id."""
    try:
        await conn.coll(_COLL).insert_one(_to_doc(m))
    except DuplicateKeyError:
        return False
    return True


async def apply_elo_update(
    conn: AtlasConn,
    *,
    match_id: str,
    hyp_a: str,
    hyp_b: str,
    winner: str,
    elo_a_before: float,
    elo_b_before: float,
    elo_a_after: float,
    elo_b_after: float,
) -> bool:
    """Apply an Elo update atomically and idempotently.

    Returns True if newly applied; False if the journal already has this match id.
    """
    applied_at = int(time.time() * 1000)

    async def txn(s) -> None:
        await conn.coll("elo_journal").insert_one(
            {
                "_id": match_id,
                "match_id": match_id,
                "hyp_a": hyp_a,
                "hyp_b": hyp_b,
                "winner": winner,
                "elo_a_before": elo_a_before,
                "elo_b_before": elo_b_before,
                "elo_a_after": elo_a_after,
                "elo_b_after": elo_b_after,
                "applied_at": applied_at,
            },
            session=s,
        )
        hyps = conn.coll("hypotheses")
        for hid, elo in ((hyp_a, elo_a_after), (hyp_b, elo_b_after)):
            await hyps.update_one(
                {"_id": hid}, {"$set": {"elo": elo}, "$inc": {"matches_played": 1}}, session=s
            )
        # reflect the after-Elo into the descriptive match row if it exists
        await conn.coll(_COLL).update_one(
            {"_id": match_id},
            {"$set": {"elo_a_after": elo_a_after, "elo_b_after": elo_b_after}},
            session=s,
        )

    try:
        async with conn.client.start_session() as s:
            # with_transaction retries TransientTransactionError / UnknownTransactionCommitResult
            await s.with_transaction(txn)
    except DuplicateKeyError:
        return False  # match id already journaled; the transaction aborted, nothing written
    return True


async def count_matches(conn: AtlasConn, session_id: str) -> int:
    return await conn.coll(_COLL).count_documents(
        {"session_id": session_id, "mode": {"$ne": "invalid"}}
    )


async def recent_rationales(conn: AtlasConn, session_id: str, limit: int = 50) -> list[str]:
    if limit <= 0:  # Mongo reads limit(0) as "no limit"
        return []
    cur = (
        conn.coll(_COLL)
        .find(
            {"session_id": session_id, "rationale": {"$ne": None}},
            {"rationale": 1},
        )
        .sort([("created_at", -1), ("_id", -1)])
        .limit(limit)
    )
    return [d["rationale"] async for d in cur]


async def list_for_session(
    conn: AtlasConn, session_id: str, *, limit: int
) -> list[TournamentMatch]:
    """Most recent matches first."""
    if limit <= 0:  # Mongo reads limit(0) as "no limit"
        return []
    cur = (
        conn.coll(_COLL)
        .find({"session_id": session_id})
        .sort([("created_at", -1), ("_id", -1)])
        .limit(limit)
    )
    return [_from_doc(d) async for d in cur]


async def list_for_hypothesis(conn: AtlasConn, hypothesis_id: str) -> list[TournamentMatch]:
    """Every match the hypothesis played, oldest first."""
    cur = (
        conn.coll(_COLL)
        .find({"$or": [{"hyp_a": hypothesis_id}, {"hyp_b": hypothesis_id}]})
        .sort([("created_at", 1), ("_id", 1)])
    )
    return [_from_doc(d) async for d in cur]


async def count_by_mode(conn: AtlasConn, session_id: str) -> dict[str, int]:
    cur = await conn.coll(_COLL).aggregate(
        [
            {"$match": {"session_id": session_id}},
            {"$group": {"_id": "$mode", "n": {"$sum": 1}}},
        ]
    )
    return {d["_id"]: d["n"] async for d in cur}
