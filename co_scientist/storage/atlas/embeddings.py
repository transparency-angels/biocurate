"""Atlas implementations for `embeddings` (collection `embeddings_meta`)."""

from __future__ import annotations

from pymongo.errors import DuplicateKeyError

from ._codec import now
from .client import AtlasConn

_COLL = "embeddings_meta"


async def upsert(
    conn: AtlasConn,
    *,
    id_: str,
    session_id: str,
    hypothesis_id: str,
    model: str,
    dim: int,
    faiss_offset: int,
    text_hash: str,
) -> None:
    # Like SQLite's ON CONFLICT(hypothesis_id, model): a repeat only refreshes
    # offset, hash and timestamp; id, session and dim keep their first values.
    update = {
        "$set": {"faiss_offset": faiss_offset, "text_hash": text_hash, "created_at": now()},
        "$setOnInsert": {"_id": id_, "session_id": session_id, "dim": dim},
    }
    key = {"hypothesis_id": hypothesis_id, "model": model}
    coll = conn.coll(_COLL)
    try:
        await coll.update_one(key, update, upsert=True)
    except DuplicateKeyError:
        # Lost an upsert race on the unique (hypothesis_id, model) index; the
        # row exists now, so a plain update applies.
        await coll.update_one(key, {"$set": update["$set"]})


async def has_embedding(conn: AtlasConn, hypothesis_id: str, model: str) -> bool:
    return (
        await conn.coll(_COLL).find_one(
            {"hypothesis_id": hypothesis_id, "model": model}, {"_id": 1}
        )
        is not None
    )


async def list_for_session(conn: AtlasConn, session_id: str) -> list[dict]:
    cur = (
        conn.coll(_COLL)
        .find({"session_id": session_id})
        .sort([("faiss_offset", 1), ("_id", 1)])
    )
    return [
        {
            "id": d["_id"],
            "hypothesis_id": d["hypothesis_id"],
            "model": d["model"],
            "dim": d["dim"],
            "faiss_offset": d["faiss_offset"],
            "text_hash": d["text_hash"],
        }
        async for d in cur
    ]


async def fetch_offset(conn: AtlasConn, hypothesis_id: str, model: str) -> int | None:
    d = await conn.coll(_COLL).find_one(
        {"hypothesis_id": hypothesis_id, "model": model}, {"faiss_offset": 1}
    )
    return d["faiss_offset"] if d else None
