"""Atlas implementations for `tasks` (stubs; filled in Tasks 4 and 5)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .client import AtlasConn

if TYPE_CHECKING:
    from ...models import Task


async def enqueue(conn: AtlasConn, task: Task) -> bool:
    """Insert a task; returns True on insert, False if idempotency_key collides."""
    raise NotImplementedError("tasks.enqueue on Atlas: Task 4/5")


async def claim_one(
    conn: AtlasConn, session_id: str, worker_id: str, lease_seconds: int
) -> Task | None:
    """Atomically claim the highest-priority pending task for a session."""
    raise NotImplementedError("tasks.claim_one on Atlas: Task 4/5")


async def heartbeat(conn: AtlasConn, task_id: str, lease_seconds: int) -> None:
    raise NotImplementedError("tasks.heartbeat on Atlas: Task 4/5")


async def mark_in_progress(conn: AtlasConn, task_id: str) -> None:
    raise NotImplementedError("tasks.mark_in_progress on Atlas: Task 4/5")


async def complete(conn: AtlasConn, task_id: str) -> None:
    raise NotImplementedError("tasks.complete on Atlas: Task 4/5")


async def fail(
    conn: AtlasConn,
    task_id: str,
    error: str,
    *,
    max_attempts: int = 3,
    requeue_backoff_seconds: list[int] | None = None,
) -> str:
    """Increment attempts; either requeue or dead-letter. Returns the final status."""
    raise NotImplementedError("tasks.fail on Atlas: Task 4/5")


async def cancel_pending_for_session(conn: AtlasConn, session_id: str) -> int:
    raise NotImplementedError("tasks.cancel_pending_for_session on Atlas: Task 4/5")


async def reclaim_expired_leases(
    conn: AtlasConn,
    session_id: str | None = None,
    *,
    max_attempts: int = 3,
) -> dict[str, int]:
    """On startup: reset expired-lease tasks; dead-letter those past max_attempts."""
    raise NotImplementedError("tasks.reclaim_expired_leases on Atlas: Task 4/5")


async def count_by_status(conn: AtlasConn, session_id: str) -> dict[str, int]:
    raise NotImplementedError("tasks.count_by_status on Atlas: Task 4/5")
