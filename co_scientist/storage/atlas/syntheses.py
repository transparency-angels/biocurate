"""Atlas implementations for `syntheses`."""

from __future__ import annotations

from typing import Any

from ._codec import now
from .client import AtlasConn

_COLL = "syntheses"


async def save(conn: AtlasConn, session_id: str, doc: dict[str, Any]) -> None:
    await conn.coll(_COLL).replace_one(
        {"_id": session_id}, {**doc, "created_at": now()}, upsert=True
    )


async def fetch(conn: AtlasConn, session_id: str) -> dict[str, Any] | None:
    d = await conn.coll(_COLL).find_one({"_id": session_id})
    if d is None:
        return None
    d.pop("_id", None)
    d.pop("created_at", None)
    return d
