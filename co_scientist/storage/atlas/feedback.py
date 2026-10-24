"""Atlas implementations for `feedback` (collection `system_feedback`)."""

from __future__ import annotations

from typing import Any

from ...models import SystemFeedback
from ._codec import aware
from .client import AtlasConn

_COLL = "system_feedback"
_NEWEST = [("created_at", -1), ("_id", -1)]


def _to_doc(f: SystemFeedback) -> dict[str, Any]:
    return {
        "_id": f.id,
        "session_id": f.session_id,
        "created_at": f.created_at,
        "source": f.source,
        "kind": f.kind,
        "target_id": f.target_id,
        "text": f.text,
        "artifact_path": f.artifact_path,
        "active": f.active,
    }


def _from_doc(d: dict[str, Any]) -> SystemFeedback:
    return SystemFeedback(
        id=d["_id"],
        session_id=d["session_id"],
        created_at=aware(d["created_at"]),
        source=d["source"],
        kind=d["kind"],
        target_id=d.get("target_id"),
        text=d["text"],
        artifact_path=d.get("artifact_path"),
        active=bool(d["active"]),
    )


async def insert(conn: AtlasConn, f: SystemFeedback) -> None:
    await conn.coll(_COLL).insert_one(_to_doc(f))


async def active_for_session(
    conn: AtlasConn, session_id: str, target_id: str | None = None
) -> list[SystemFeedback]:
    """Return active feedback. If `target_id` is given, include targeted matches *plus* global."""
    flt: dict[str, Any] = {"session_id": session_id, "active": True}
    if target_id:
        flt["$or"] = [{"target_id": None}, {"target_id": target_id}]
    else:
        flt["target_id"] = None
    cur = conn.coll(_COLL).find(flt).sort(_NEWEST)
    return [_from_doc(d) async for d in cur]


async def latest_system_feedback(conn: AtlasConn, session_id: str) -> SystemFeedback | None:
    d = await conn.coll(_COLL).find_one(
        {"session_id": session_id, "kind": "system_feedback", "source": "meta_review"},
        sort=_NEWEST,
    )
    return _from_doc(d) if d else None


async def deactivate(conn: AtlasConn, feedback_id: str) -> None:
    await conn.coll(_COLL).update_one({"_id": feedback_id}, {"$set": {"active": False}})


async def count_meta_review(conn: AtlasConn, session_id: str) -> int:
    return await conn.coll(_COLL).count_documents(
        {"session_id": session_id, "kind": "system_feedback", "source": "meta_review"}
    )
