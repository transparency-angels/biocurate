"""Atlas implementations for `reviews` (stubs; filled in Tasks 4 and 5)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .client import AtlasConn

if TYPE_CHECKING:
    from ...models import Review


async def insert(conn: AtlasConn, r: Review) -> bool:
    raise NotImplementedError("reviews.insert on Atlas: Task 4/5")


async def fetch(conn: AtlasConn, review_id: str) -> Review | None:
    raise NotImplementedError("reviews.fetch on Atlas: Task 4/5")


async def list_for_hypothesis(conn: AtlasConn, hypothesis_id: str) -> list[Review]:
    raise NotImplementedError("reviews.list_for_hypothesis on Atlas: Task 4/5")


async def list_for_session(conn: AtlasConn, session_id: str) -> list[Review]:
    raise NotImplementedError("reviews.list_for_session on Atlas: Task 4/5")
