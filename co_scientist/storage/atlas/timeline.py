"""Atlas implementations for `timeline`."""

from __future__ import annotations

from typing import Any

from pymongo import ReturnDocument

from ...models.timeline import TimelineMessage, TimelineRole
from ._codec import aware, now
from .client import AtlasConn

_COLL = "timeline"
_COUNTERS = "timeline_counters"


def _from_doc(d: dict[str, Any]) -> TimelineMessage:
    return TimelineMessage(
        session_id=d["session_id"],
        seq=d["seq"],
        ts=aware(d["ts"]),
        role=d["role"],
        agent=d.get("agent"),
        kind=d["kind"],
        title=d["title"],
        body_markdown=d["body_markdown"],
        refs=list(d.get("refs", [])),
    )


async def append(
    conn: AtlasConn,
    session_id: str,
    *,
    role: TimelineRole,
    agent: str | None,
    kind: str,
    title: str,
    body_markdown: str,
    refs: list[str],
) -> TimelineMessage:
    """Insert with the next per-session `seq` from an atomic counter."""
    c = await conn.coll(_COUNTERS).find_one_and_update(
        {"_id": session_id},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    seq = int(c["seq"])
    ts = now()
    await conn.coll(_COLL).insert_one(
        {
            "session_id": session_id, "seq": seq, "ts": ts, "role": role, "agent": agent,
            "kind": kind, "title": title, "body_markdown": body_markdown, "refs": list(refs),
        }
    )
    return TimelineMessage(
        session_id=session_id, seq=seq, ts=ts, role=role, agent=agent,
        kind=kind, title=title, body_markdown=body_markdown, refs=list(refs),
    )


async def list_for_session(
    conn: AtlasConn, session_id: str, *, after_seq: int = 0, limit: int = 500
) -> list[TimelineMessage]:
    cur = (
        conn.coll(_COLL)
        .find({"session_id": session_id, "seq": {"$gt": after_seq}})
        .sort("seq", 1)
        .limit(limit)
    )
    return [_from_doc(d) async for d in cur]
