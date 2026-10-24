"""Atlas implementations for `transcripts` (stubs; filled in Tasks 4 and 5)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .client import AtlasConn

if TYPE_CHECKING:
    from ...models import Transcript


async def insert(conn: AtlasConn, t: Transcript) -> None:
    raise NotImplementedError("transcripts.insert on Atlas: Task 4/5")


async def usage_summary(conn: AtlasConn, session_id: str) -> dict[str, float | int]:
    raise NotImplementedError("transcripts.usage_summary on Atlas: Task 4/5")


async def durations_ms(conn: AtlasConn, session_id: str) -> list[float]:
    """Per-call latency in ms, ascending (rough: whole-second resolution)."""
    raise NotImplementedError("transcripts.durations_ms on Atlas: Task 4/5")
