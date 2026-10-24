"""Atlas implementations for `hypotheses` (stubs; filled in Tasks 4 and 5)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .client import AtlasConn

if TYPE_CHECKING:
    from ...models import Hypothesis


async def insert(conn: AtlasConn, h: Hypothesis) -> bool:
    """Insert; returns True if a new row was created, False if it already existed."""
    raise NotImplementedError("hypotheses.insert on Atlas: Task 4/5")


async def fetch(conn: AtlasConn, hypothesis_id: str) -> Hypothesis | None:
    raise NotImplementedError("hypotheses.fetch on Atlas: Task 4/5")


async def fetch_many(conn: AtlasConn, ids: list[str]) -> list[Hypothesis]:
    raise NotImplementedError("hypotheses.fetch_many on Atlas: Task 4/5")


async def list_for_session(
    conn: AtlasConn, session_id: str, state: str | None = None
) -> list[Hypothesis]:
    raise NotImplementedError("hypotheses.list_for_session on Atlas: Task 4/5")


async def top_by_elo(conn: AtlasConn, session_id: str, k: int = 10) -> list[Hypothesis]:
    raise NotImplementedError("hypotheses.top_by_elo on Atlas: Task 4/5")


async def count_by_state(conn: AtlasConn, session_id: str) -> dict[str, int]:
    raise NotImplementedError("hypotheses.count_by_state on Atlas: Task 4/5")


async def elo_range(conn: AtlasConn, session_id: str) -> tuple[float | None, float | None, int]:
    """(min elo, max elo, number of hypotheses with an elo)."""
    raise NotImplementedError("hypotheses.elo_range on Atlas: Task 4/5")


async def top_elo_ids(conn: AtlasConn, session_id: str, k: int) -> list[tuple[str, float]]:
    raise NotImplementedError("hypotheses.top_elo_ids on Atlas: Task 4/5")


async def pool_size(conn: AtlasConn, session_id: str) -> int:
    raise NotImplementedError("hypotheses.pool_size on Atlas: Task 4/5")


async def set_state(conn: AtlasConn, hypothesis_id: str, state: str) -> None:
    raise NotImplementedError("hypotheses.set_state on Atlas: Task 4/5")


async def set_state_if(
    conn: AtlasConn,
    hypothesis_id: str,
    *,
    new_state: str,
    expected_states: tuple[str, ...],
) -> bool:
    """Conditional state transition. Returns True if applied."""
    raise NotImplementedError("hypotheses.set_state_if on Atlas: Task 4/5")


async def init_tournament(conn: AtlasConn, hypothesis_id: str, initial_elo: float = 1200.0) -> bool:
    """Set Elo and state if not already in tournament; returns True if applied."""
    raise NotImplementedError("hypotheses.init_tournament on Atlas: Task 4/5")


async def set_dedup_cluster(conn: AtlasConn, hypothesis_id: str, cluster: str | None) -> None:
    raise NotImplementedError("hypotheses.set_dedup_cluster on Atlas: Task 4/5")
