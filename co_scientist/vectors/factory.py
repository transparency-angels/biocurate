"""Pick the vector store implementation for the active storage backend."""

from __future__ import annotations

from ..config import Config
from ..storage import Conn
from ..storage.atlas.client import AtlasConn
from .base import VectorStore


def make_vector_store(cfg: Config, db: Conn, session_id: str, dim: int) -> VectorStore:
    if isinstance(db, AtlasConn):
        # Lazy import: the Atlas implementation is added in Task 7.
        raise NotImplementedError("AtlasVectorStore: Task 7")
    from .store import FaissStore

    return FaissStore(cfg, session_id, dim=dim)
