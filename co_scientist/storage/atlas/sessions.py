"""Atlas implementations for `sessions` (stubs; filled in Tasks 4 and 5)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .client import AtlasConn

if TYPE_CHECKING:
    from ...models import Session


async def insert(conn: AtlasConn, s: Session) -> None:
    raise NotImplementedError("sessions.insert on Atlas: Task 4/5")


async def fetch(conn: AtlasConn, session_id: str) -> Session | None:
    raise NotImplementedError("sessions.fetch on Atlas: Task 4/5")


async def fetch_row(conn: AtlasConn, session_id: str) -> dict | None:
    """Raw session row as a plain dict (stored strings untouched)."""
    raise NotImplementedError("sessions.fetch_row on Atlas: Task 4/5")


async def set_status(conn: AtlasConn, session_id: str, status: str) -> None:
    raise NotImplementedError("sessions.set_status on Atlas: Task 4/5")


async def add_usage(conn: AtlasConn, session_id: str, tokens: int, usd: float) -> None:
    raise NotImplementedError("sessions.add_usage on Atlas: Task 4/5")


async def set_final_overview(conn: AtlasConn, session_id: str, rel_path: str) -> None:
    raise NotImplementedError("sessions.set_final_overview on Atlas: Task 4/5")


async def list_with_stats(conn: AtlasConn, *, limit: int | None = None) -> list[dict]:
    """Sessions newest-updated first, with hypothesis count and best Elo."""
    raise NotImplementedError("sessions.list_with_stats on Atlas: Task 4/5")


async def ids_created_since(conn: AtlasConn, iso_ts: str) -> list[str]:
    raise NotImplementedError("sessions.ids_created_since on Atlas: Task 4/5")


async def ids_for_goal(conn: AtlasConn, goal: str) -> list[str]:
    """Session ids with exactly this research goal, newest first."""
    raise NotImplementedError("sessions.ids_for_goal on Atlas: Task 4/5")


async def set_research_plan(conn: AtlasConn, session_id: str, plan: dict) -> None:
    raise NotImplementedError("sessions.set_research_plan on Atlas: Task 4/5")
