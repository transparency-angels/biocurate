"""Atlas implementations for `tournaments`.

`record_match_result` reads the current ratings, computes the Elo update and writes it in
one multi-document transaction guarded by the `_id` of the `elo_journal` document (= match
id), so re-applying the same match is a no-op and overlapping matches are retried.
"""

from __future__ import annotations

import time
from typing import Any

from pymongo.errors import DuplicateKeyError

from ...models import TournamentMatch
from ...orchestrator.elo import AppliedElo, update_elo
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


async def record_match_result(
    conn: AtlasConn,
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

    Everything, including the reads, runs in one transaction. If another transaction
    updates the same hypothesis first, the write raises a WriteConflict (a
    TransientTransactionError), `with_transaction` re-runs the callback, and the re-read
    sees the committed values, so no update is lost. Returns None if the journal already
    has this match id; raises ValueError (nothing written) if a hypothesis is missing.
    """

    async def txn(s) -> AppliedElo:
        applied_at = int(time.time() * 1000)  # per attempt, so a retry stamps its own time
        hyps = conn.coll("hypotheses")
        cur: dict[str, tuple[float, int]] = {}
        for hid in (hyp_a, hyp_b):
            d = await hyps.find_one(
                {"_id": hid}, {"elo": 1, "matches_played": 1}, session=s
            )
            if d is None:
                raise ValueError(f"no such hypothesis: {hid}")
            elo = d.get("elo")
            cur[hid] = (initial_elo if elo is None else float(elo), d["matches_played"])
        (elo_a, mp_a), (elo_b, mp_b) = cur[hyp_a], cur[hyp_b]
        upd = update_elo(elo_a, elo_b, winner, min(mp_a, mp_b), k_new=k_new, k_warm=k_warm)
        await conn.coll("elo_journal").insert_one(
            {
                "_id": match_id,
                "match_id": match_id,
                "hyp_a": hyp_a,
                "hyp_b": hyp_b,
                "winner": winner,
                "elo_a_before": elo_a,
                "elo_b_before": elo_b,
                "elo_a_after": upd.elo_a_after,
                "elo_b_after": upd.elo_b_after,
                "applied_at": applied_at,
            },
            session=s,
        )
        for hid, elo_after in ((hyp_a, upd.elo_a_after), (hyp_b, upd.elo_b_after)):
            await hyps.update_one(
                {"_id": hid},
                {"$set": {"elo": elo_after}, "$inc": {"matches_played": 1}},
                session=s,
            )
        # reflect the in-transaction values into the descriptive match row if it exists
        await conn.coll(_COLL).update_one(
            {"_id": match_id},
            {
                "$set": {
                    "elo_a_before": elo_a,
                    "elo_b_before": elo_b,
                    "elo_a_after": upd.elo_a_after,
                    "elo_b_after": upd.elo_b_after,
                }
            },
            session=s,
        )
        return AppliedElo(
            elo_a_before=elo_a, elo_b_before=elo_b,
            elo_a_after=upd.elo_a_after, elo_b_after=upd.elo_b_after,
            k=upd.k, expected_a=upd.expected_a,
        )

    try:
        async with conn.client.start_session() as s:
            # with_transaction retries TransientTransactionError / UnknownTransactionCommitResult
            return await s.with_transaction(txn)
    except DuplicateKeyError:
        return None  # match id already journaled; the transaction aborted, nothing written


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
