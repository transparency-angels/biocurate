"""Atlas implementations for `tournaments` (stubs; filled in Tasks 4 and 5)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .client import AtlasConn

if TYPE_CHECKING:
    from ...models import TournamentMatch


async def insert_match(conn: AtlasConn, m: TournamentMatch) -> bool:
    """Insert the descriptive match row. Idempotent by id."""
    raise NotImplementedError("tournaments.insert_match on Atlas: Task 4/5")


async def apply_elo_update(
    conn: AtlasConn,
    *,
    match_id: str,
    hyp_a: str,
    hyp_b: str,
    winner: str,
    elo_a_before: float,
    elo_b_before: float,
    elo_a_after: float,
    elo_b_after: float,
) -> bool:
    """Apply an Elo update atomically and idempotently."""
    raise NotImplementedError("tournaments.apply_elo_update on Atlas: Task 4/5")


async def count_matches(conn: AtlasConn, session_id: str) -> int:
    raise NotImplementedError("tournaments.count_matches on Atlas: Task 4/5")


async def recent_rationales(conn: AtlasConn, session_id: str, limit: int = 50) -> list[str]:
    raise NotImplementedError("tournaments.recent_rationales on Atlas: Task 4/5")


async def list_for_session(
    conn: AtlasConn, session_id: str, *, limit: int
) -> list[TournamentMatch]:
    """Most recent matches first."""
    raise NotImplementedError("tournaments.list_for_session on Atlas: Task 4/5")


async def list_for_hypothesis(conn: AtlasConn, hypothesis_id: str) -> list[TournamentMatch]:
    """Every match the hypothesis played, oldest first."""
    raise NotImplementedError("tournaments.list_for_hypothesis on Atlas: Task 4/5")


async def count_by_mode(conn: AtlasConn, session_id: str) -> dict[str, int]:
    raise NotImplementedError("tournaments.count_by_mode on Atlas: Task 4/5")
