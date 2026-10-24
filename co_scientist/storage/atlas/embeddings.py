"""Atlas implementations for `embeddings` (stubs; filled in Tasks 4 and 5)."""

from __future__ import annotations

from .client import AtlasConn


async def upsert(
    conn: AtlasConn,
    *,
    id_: str,
    session_id: str,
    hypothesis_id: str,
    model: str,
    dim: int,
    faiss_offset: int,
    text_hash: str,
) -> None:
    raise NotImplementedError("embeddings.upsert on Atlas: Task 4/5")


async def has_embedding(conn: AtlasConn, hypothesis_id: str, model: str) -> bool:
    raise NotImplementedError("embeddings.has_embedding on Atlas: Task 4/5")


async def list_for_session(conn: AtlasConn, session_id: str) -> list[dict]:
    raise NotImplementedError("embeddings.list_for_session on Atlas: Task 4/5")


async def fetch_offset(conn: AtlasConn, hypothesis_id: str, model: str) -> int | None:
    raise NotImplementedError("embeddings.fetch_offset on Atlas: Task 4/5")
