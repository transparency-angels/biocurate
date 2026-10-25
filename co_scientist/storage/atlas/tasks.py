"""Atlas implementations for `tasks` (durable queue; atomic claim via findAndModify)."""

from __future__ import annotations

import time
from typing import Any

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from ...models import Task
from ._codec import aware, now
from .client import AtlasConn

_COLL = "tasks"
_ACTIVE = ["leased", "in_progress"]


def _epoch_ms() -> int:
    return int(time.time() * 1000)


def _to_doc(t: Task) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "_id": t.id,
        "session_id": t.session_id,
        "created_at": t.created_at,
        "started_at": t.started_at,
        "finished_at": t.finished_at,
        "agent": t.agent,
        "action": t.action,
        "target_id": t.target_id,
        "payload": t.payload,
        "priority": t.priority,
        "status": t.status,
        "lease_owner": t.lease_owner,
        "lease_expires_at": t.lease_expires_at,  # epoch ms, as in SQLite
        "attempts": t.attempts,
        "last_error": t.last_error,
    }
    if t.idempotency_key is not None:  # the unique index only covers string keys
        doc["idempotency_key"] = t.idempotency_key
    return doc


def _opt_aware(dt):
    return None if dt is None else aware(dt)


def _from_doc(d: dict[str, Any]) -> Task:
    return Task(
        id=d["_id"],
        session_id=d["session_id"],
        created_at=aware(d["created_at"]),
        started_at=_opt_aware(d.get("started_at")),
        finished_at=_opt_aware(d.get("finished_at")),
        agent=d["agent"],
        action=d["action"],
        target_id=d.get("target_id"),
        payload=d.get("payload") or {},
        priority=d["priority"],
        status=d["status"],
        lease_owner=d.get("lease_owner"),
        lease_expires_at=d.get("lease_expires_at"),
        attempts=d["attempts"],
        last_error=d.get("last_error"),
        idempotency_key=d.get("idempotency_key"),
    )


async def enqueue(conn: AtlasConn, task: Task) -> bool:
    """Insert a task; returns True on insert, False if idempotency_key collides."""
    try:
        await conn.coll(_COLL).insert_one(_to_doc(task))
    except DuplicateKeyError:  # on _id or the unique idempotency_key
        return False
    return True


async def claim_one(
    conn: AtlasConn, session_id: str, worker_id: str, lease_seconds: int
) -> Task | None:
    """Atomically claim the highest-priority pending task for a session."""
    d = await conn.coll(_COLL).find_one_and_update(
        {"session_id": session_id, "status": "pending"},
        {
            "$set": {
                "status": "leased",
                "lease_owner": worker_id,
                "lease_expires_at": _epoch_ms() + lease_seconds * 1000,
                "started_at": now(),
            }
        },
        sort=[("priority", 1), ("created_at", 1), ("_id", 1)],
        return_document=ReturnDocument.AFTER,
    )
    return _from_doc(d) if d else None


async def heartbeat(conn: AtlasConn, task_id: str, lease_seconds: int) -> None:
    await conn.coll(_COLL).update_one(
        {"_id": task_id, "status": {"$in": _ACTIVE}},
        {"$set": {"lease_expires_at": _epoch_ms() + lease_seconds * 1000}},
    )


async def mark_in_progress(conn: AtlasConn, task_id: str) -> None:
    await conn.coll(_COLL).update_one({"_id": task_id}, {"$set": {"status": "in_progress"}})


async def complete(conn: AtlasConn, task_id: str) -> None:
    await conn.coll(_COLL).update_one(
        {"_id": task_id}, {"$set": {"status": "done", "finished_at": now()}}
    )


async def fail(
    conn: AtlasConn,
    task_id: str,
    error: str,
    *,
    max_attempts: int = 3,
    requeue_backoff_seconds: list[int] | None = None,
) -> str:
    """Increment attempts; either requeue or dead-letter. Returns the final status."""
    _ = requeue_backoff_seconds  # backoff is enforced cooperatively by the scheduler
    # One atomic pipeline update. Every `$attempts` in a stage reads the pre-update value,
    # so the status test uses attempts + 1 against max_attempts, as SQLite does.
    new_attempts = {"$add": ["$attempts", 1]}
    is_dead = {"$gte": [new_attempts, max_attempts]}

    def per_branch(dead: Any, pending: Any) -> dict[str, Any]:
        return {"$cond": [is_dead, dead, pending]}

    d = await conn.coll(_COLL).find_one_and_update(
        {"_id": task_id},
        [
            {
                "$set": {
                    "attempts": new_attempts,
                    "status": per_branch("dead", "pending"),
                    "last_error": {"$literal": error[:4000]},
                    "finished_at": per_branch(now(), "$finished_at"),
                    "lease_owner": per_branch("$lease_owner", None),
                    "lease_expires_at": per_branch("$lease_expires_at", None),
                    "started_at": per_branch("$started_at", None),
                }
            }
        ],
        projection={"status": 1},
        return_document=ReturnDocument.AFTER,
    )
    return "missing" if d is None else d["status"]


async def cancel_pending_for_session(conn: AtlasConn, session_id: str) -> int:
    res = await conn.coll(_COLL).update_many(
        {"session_id": session_id, "status": "pending"}, {"$set": {"status": "cancelled"}}
    )
    return res.matched_count


async def reclaim_expired_leases(
    conn: AtlasConn,
    session_id: str | None = None,
    *,
    max_attempts: int = 3,
) -> dict[str, int]:
    """On startup: reset expired-lease tasks; dead-letter those past max_attempts.

    Returns {"requeued": n, "dead": m}. Both steps are server-side pipeline updates,
    dead-letter first so the requeue step only sees what is left.
    """
    coll = conn.coll(_COLL)
    expired: dict[str, Any] = {
        "status": {"$in": _ACTIVE},
        "lease_expires_at": {"$lt": _epoch_ms()},  # null/missing never compares < number
    }
    if session_id:
        expired["session_id"] = session_id
    suffix = lambda s: {"$concat": [{"$ifNull": ["$last_error", ""]}, s]}  # noqa: E731
    bump = {"$add": ["$attempts", 1]}

    dead = await coll.update_many(
        {**expired, "$expr": {"$gte": [bump, max_attempts]}},
        [
            {
                "$set": {
                    "status": "dead",
                    "attempts": bump,
                    "finished_at": now(),
                    "last_error": suffix(" [lease expired; max attempts]"),
                }
            }
        ],
    )
    req = await coll.update_many(
        expired,
        [
            {
                "$set": {
                    "status": "pending",
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "started_at": None,
                    "attempts": bump,
                    "last_error": suffix(" [lease expired]"),
                }
            }
        ],
    )
    return {"requeued": req.matched_count, "dead": dead.matched_count}


async def count_by_status(conn: AtlasConn, session_id: str) -> dict[str, int]:
    cur = await conn.coll(_COLL).aggregate(
        [
            {"$match": {"session_id": session_id}},
            {"$group": {"_id": "$status", "n": {"$sum": 1}}},
        ]
    )
    return {d["_id"]: d["n"] async for d in cur}


async def list_for_session(conn: AtlasConn, session_id: str) -> list[Task]:
    """All tasks for reconstructing a session's progress after a client reconnects."""
    cur = conn.coll(_COLL).find({"session_id": session_id}).sort(
        [("created_at", 1), ("_id", 1)]
    )
    return [_from_doc(d) async for d in cur]
