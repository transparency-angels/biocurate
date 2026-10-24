"""Atlas implementations for `feedback` (stubs; filled in Tasks 4 and 5)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .client import AtlasConn

if TYPE_CHECKING:
    from ...models import SystemFeedback


async def insert(conn: AtlasConn, f: SystemFeedback) -> None:
    raise NotImplementedError("feedback.insert on Atlas: Task 4/5")


async def active_for_session(
    conn: AtlasConn, session_id: str, target_id: str | None = None
) -> list[SystemFeedback]:
    """Return active feedback. If `target_id` is given, include targeted matches *plus* global."""
    raise NotImplementedError("feedback.active_for_session on Atlas: Task 4/5")


async def latest_system_feedback(conn: AtlasConn, session_id: str) -> SystemFeedback | None:
    raise NotImplementedError("feedback.latest_system_feedback on Atlas: Task 4/5")


async def deactivate(conn: AtlasConn, feedback_id: str) -> None:
    raise NotImplementedError("feedback.deactivate on Atlas: Task 4/5")


async def count_meta_review(conn: AtlasConn, session_id: str) -> int:
    raise NotImplementedError("feedback.count_meta_review on Atlas: Task 4/5")
