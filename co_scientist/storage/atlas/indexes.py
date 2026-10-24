"""Index bootstrap for the Atlas backend.

B-tree indexes mirror `schema.sql`. Atlas Search / Vector Search indexes are
declared in `SEARCH_INDEX_SPECS` (other modules append to it) and are created
only when missing by name; existing ones are never updated or dropped.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from pymongo import ASCENDING, DESCENDING, IndexModel
from pymongo.operations import SearchIndexModel

if TYPE_CHECKING:
    from ...config import Config
    from .client import AtlasConn


@dataclass(frozen=True)
class SearchIndexSpec:
    collection: str
    name: str
    type: Literal["search", "vectorSearch"]
    definition: Callable[[Config], dict]


SEARCH_INDEX_SPECS: list[SearchIndexSpec] = []

_A, _D = ASCENDING, DESCENDING

BTREE_INDEXES: dict[str, list[IndexModel]] = {
    "sessions": [IndexModel([("status", _A), ("updated_at", _D)], name="sessions_status")],
    "hypotheses": [
        IndexModel([("session_id", _A), ("elo", _D)], name="hyp_sess_elo"),
        IndexModel([("session_id", _A), ("state", _A)], name="hyp_sess_state"),
    ],
    "reviews": [IndexModel([("hypothesis_id", _A), ("created_at", _D)], name="rev_hyp")],
    "tasks": [
        IndexModel(
            [("session_id", _A), ("status", _A), ("priority", _A), ("created_at", _A)],
            name="tasks_queue",
        ),
        IndexModel(
            [("idempotency_key", _A)],
            name="tasks_idempotency_key",
            unique=True,
            partialFilterExpression={"idempotency_key": {"$type": "string"}},
        ),
    ],
    "tournament_matches": [
        IndexModel([("session_id", _A), ("created_at", _D)], name="mat_sess"),
        IndexModel([("hyp_a", _A), ("created_at", _A)], name="mat_hyp_a"),
        IndexModel([("hyp_b", _A), ("created_at", _A)], name="mat_hyp_b"),
    ],
    "transcripts": [IndexModel([("session_id", _A), ("started_at", _D)], name="trn_sess")],
    "system_feedback": [
        IndexModel([("session_id", _A), ("active", _A), ("created_at", _D)], name="fb_sess_active")
    ],
    "events": [
        IndexModel([("session_id", _A), ("ts", _D)], name="events_sess"),
        IndexModel([("event", _A), ("ts", _D)], name="events_type"),
    ],
    "spans": [IndexModel([("trace_id", _A)], name="spans_trace")],
    "embeddings_meta": [
        IndexModel([("hypothesis_id", _A), ("model", _A)], name="emb_hyp_model", unique=True)
    ],
    "library": [IndexModel([("pmcid", _A)], name="library_pmcid")],
}


async def _existing_search_names(coll: Any) -> set[str]:
    cur = await coll.list_search_indexes()
    return {d["name"] for d in await cur.to_list()}


async def ensure_indexes(conn: AtlasConn, cfg: Config) -> None:
    """Idempotently create B-tree indexes and any missing search indexes."""
    for name, models in BTREE_INDEXES.items():
        await conn.coll(name).create_indexes(models)

    by_coll: dict[str, list[SearchIndexSpec]] = {}
    for spec in SEARCH_INDEX_SPECS:
        by_coll.setdefault(spec.collection, []).append(spec)
    for cname, specs in by_coll.items():
        await conn.ensure_collection(cname)
        coll = conn.coll(cname)
        have = await _existing_search_names(coll)
        for spec in specs:
            if spec.name in have:
                continue
            await coll.create_search_index(
                SearchIndexModel(definition=spec.definition(cfg), name=spec.name, type=spec.type)
            )


async def wait_for_search_index(
    coll: Any, name: str, *, timeout_s: float = 600, poll_s: float = 5
) -> bool:
    """Poll until the named search index is queryable; False on timeout."""
    deadline = time.monotonic() + timeout_s
    while True:
        cur = await coll.list_search_indexes(name)
        if any(d.get("queryable") for d in await cur.to_list()):
            return True
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(min(poll_s, max(0.0, deadline - time.monotonic())))
