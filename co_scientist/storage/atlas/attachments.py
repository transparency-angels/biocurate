"""Atlas implementations for `attachments`."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pymongo.errors import DuplicateKeyError

from ...models.attachment import AttachmentMeta
from ._codec import aware
from .client import AtlasConn

_COLL = "attachments_meta"  # `attachments.files/.chunks` belong to the GridFS bucket


def _to_doc(m: AttachmentMeta) -> dict[str, Any]:
    return {
        "_id": m.id,
        "session_id": m.session_id,
        "filename": m.filename,
        "content_type": m.content_type,
        "size": m.size,
        "sha256": m.sha256,
        "kind": m.kind,
        "status": m.status,
        "blob_id": m.blob_id,
        "uploaded_at": aware(m.uploaded_at),
        "error": m.error,
    }


def _from_doc(d: dict[str, Any]) -> AttachmentMeta:
    return AttachmentMeta(
        id=d["_id"],
        session_id=d["session_id"],
        filename=d["filename"],
        content_type=d["content_type"],
        size=d["size"],
        sha256=d["sha256"],
        kind=d["kind"],
        status=d["status"],
        blob_id=d["blob_id"],
        uploaded_at=aware(d["uploaded_at"]),
        error=d.get("error"),
    )


async def insert(conn: AtlasConn, meta: AttachmentMeta) -> bool:
    """Insert; False if `(session_id, sha256, filename)` already exists."""
    try:
        await conn.coll(_COLL).insert_one(_to_doc(meta))
    except DuplicateKeyError:
        return False
    return True


async def list_for_session(conn: AtlasConn, session_id: str) -> list[AttachmentMeta]:
    cur = conn.coll(_COLL).find({"session_id": session_id}).sort([("uploaded_at", 1), ("_id", 1)])
    return [_from_doc(d) async for d in cur]


async def fetch(conn: AtlasConn, attachment_id: str) -> AttachmentMeta | None:
    d = await conn.coll(_COLL).find_one({"_id": attachment_id})
    return _from_doc(d) if d else None


async def set_status(
    conn: AtlasConn, attachment_id: str, status: str, error: str | None = None
) -> None:
    await conn.coll(_COLL).update_one(
        {"_id": attachment_id}, {"$set": {"status": status, "error": error}}
    )


async def _sum(conn: AtlasConn, match: dict[str, Any]) -> int:
    cur = await conn.coll(_COLL).aggregate(
        [{"$match": match}, {"$group": {"_id": None, "n": {"$sum": "$size"}}}]
    )
    rows = await cur.to_list()
    return int(rows[0]["n"]) if rows else 0


async def session_bytes(conn: AtlasConn, session_id: str) -> int:
    return await _sum(conn, {"session_id": session_id})


async def total_bytes(conn: AtlasConn) -> int:
    return await _sum(conn, {})


async def older_than(conn: AtlasConn, cutoff: datetime) -> list[AttachmentMeta]:
    cur = conn.coll(_COLL).find({"uploaded_at": {"$lt": aware(cutoff)}}).sort(
        [("uploaded_at", 1), ("_id", 1)]
    )
    return [_from_doc(d) async for d in cur]


async def delete(conn: AtlasConn, attachment_id: str) -> None:
    """Remove the metadata doc only; callers delete the blob."""
    await conn.coll(_COLL).delete_one({"_id": attachment_id})
