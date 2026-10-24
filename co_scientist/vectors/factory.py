"""Pick the vector store implementation for the active storage backend."""

from __future__ import annotations

from ..config import Config
from ..storage import Conn
from ..storage.atlas.client import AtlasConn
from .base import VectorStore


def make_vector_store(cfg: Config, db: Conn, session_id: str, dim: int) -> VectorStore:
    if isinstance(db, AtlasConn):
        from .atlas_store import AtlasVectorStore

        return AtlasVectorStore(cfg, db, session_id, dim)
    from .store import FaissStore

    return FaissStore(cfg, session_id, dim=dim)
