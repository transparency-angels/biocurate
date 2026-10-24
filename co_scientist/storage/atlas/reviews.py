"""Atlas implementations for `reviews`."""

from __future__ import annotations

from typing import Any

from pymongo.errors import DuplicateKeyError

from ...models import Review, ReviewScores
from ._codec import aware
from .client import AtlasConn

_COLL = "reviews"


def _to_doc(r: Review) -> dict[str, Any]:
    # Assumptions and evidence live in the JSON artifact, not the row (as in SQLite).
    return {
        "_id": r.id,
        "hypothesis_id": r.hypothesis_id,
        "session_id": r.session_id,
        "created_at": r.created_at,
        "kind": r.kind,
        "verdict": r.verdict,
        "scores": r.scores.model_dump(),
        "body": r.body,
        "artifact_path": r.artifact_path,
    }


def _from_doc(d: dict[str, Any]) -> Review:
    return Review(
        id=d["_id"],
        hypothesis_id=d["hypothesis_id"],
        session_id=d["session_id"],
        created_at=aware(d["created_at"]),
        kind=d["kind"],
        verdict=d.get("verdict"),
        scores=ReviewScores(**(d.get("scores") or {})),
        assumptions=[],
        evidence=[],
        body=d["body"],
        artifact_path=d["artifact_path"],
    )


async def insert(conn: AtlasConn, r: Review) -> bool:
    try:
        await conn.coll(_COLL).insert_one(_to_doc(r))
    except DuplicateKeyError:
        return False
    return True


async def fetch(conn: AtlasConn, review_id: str) -> Review | None:
    d = await conn.coll(_COLL).find_one({"_id": review_id})
    return _from_doc(d) if d else None


async def list_for_hypothesis(conn: AtlasConn, hypothesis_id: str) -> list[Review]:
    cur = (
        conn.coll(_COLL)
        .find({"hypothesis_id": hypothesis_id})
        .sort([("created_at", -1), ("_id", -1)])
    )
    return [_from_doc(d) async for d in cur]


async def list_for_session(conn: AtlasConn, session_id: str) -> list[Review]:
    cur = (
        conn.coll(_COLL)
        .find({"session_id": session_id})
        .sort([("created_at", -1), ("_id", -1)])
    )
    return [_from_doc(d) async for d in cur]
