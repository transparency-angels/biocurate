"""Atlas implementations for `spans` (`_id` is the span id)."""

from __future__ import annotations

import time
from typing import Any

from ...ids import span_id as new_span_id
from .client import AtlasConn

_COLL = "spans"


async def start(
    conn: AtlasConn,
    *,
    trace_id: str,
    parent_span_id: str | None,
    session_id: str | None,
    task_id: str | None,
    name: str,
    attrs: dict[str, Any] | None = None,
) -> str:
    sid = new_span_id()
    await conn.coll(_COLL).insert_one(
        {
            "_id": sid,
            "trace_id": trace_id,
            "parent_span_id": parent_span_id,
            "session_id": session_id,
            "task_id": task_id,
            "name": name,
            "started_at": int(time.time() * 1000),
            "ended_at": None,
            "attrs": attrs or {},
            "status": "unset",
        }
    )
    return sid


async def end(
    conn: AtlasConn,
    span_id_: str,
    *,
    status: str = "ok",
    attrs: dict[str, Any] | None = None,
) -> None:
    fields: dict[str, Any] = {"ended_at": int(time.time() * 1000), "status": status}
    if attrs is None:
        await conn.coll(_COLL).update_one({"_id": span_id_}, {"$set": fields})
        return
    # Server-side merge (new keys win). `$literal` stops `$`-prefixed strings in
    # the values from being read as expressions.
    fields["attrs"] = {"$mergeObjects": ["$attrs", {"$literal": attrs}]}
    await conn.coll(_COLL).update_one({"_id": span_id_}, [{"$set": fields}])
