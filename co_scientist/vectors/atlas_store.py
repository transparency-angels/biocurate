"""Hypothesis vector store on Atlas Vector Search.

The session's vectors are mirrored in memory (tens to hundreds of rows), so
`similarity`, `cosine_matrix` and `ids` stay synchronous and exact. `search`
asks `$vectorSearch` and merges exact dot products for vectors added in the
last `RECENT_WINDOW_S` seconds, because the index lags writes. If the index is
missing or still building, it falls back to an exact in-memory search.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import numpy as np
from pymongo.errors import PyMongoError

from ..config import Config
from ..logging import get_logger

if TYPE_CHECKING:
    from ..storage.atlas.client import AtlasConn

COLLECTION = "hypothesis_vectors"
INDEX_NAME = "hyp_vec"
RECENT_WINDOW_S = 30.0  # index lag: newer vectors are scored exactly in memory


def vector_score_to_cosine(score: float) -> float:
    """Atlas `vectorSearchScore` for dotProduct is (1 + cos) / 2."""
    return 2.0 * score - 1.0


class AtlasVectorStore:
    def __init__(self, cfg: Config, conn: AtlasConn, session_id: str, dim: int) -> None:
        self.cfg = cfg
        self.conn = conn
        self.session_id = session_id
        self.dim = dim
        self._ordered_ids: list[str] = []  # like FaissStore: a re-add appends a row
        self._rows: list[np.ndarray] = []
        self._row_by_id: dict[str, int] = {}  # latest row per id
        self._added_at: dict[str, float] = {}  # monotonic time of the latest add
        self._lock = asyncio.Lock()

    @property
    def n(self) -> int:
        return len(self._ordered_ids)

    async def load_or_create(self) -> None:
        cur = self.conn.coll(COLLECTION).find({"session_id": self.session_id})
        docs = await cur.to_list()
        docs.sort(key=lambda d: (d.get("created_at") or datetime.min, str(d["_id"])))
        self._ordered_ids, self._rows = [], []
        self._row_by_id, self._added_at = {}, {}
        for d in docs:
            vec = np.asarray(d["embedding"], dtype="float32")
            if vec.shape != (self.dim,):
                continue  # written under another dim/model: unusable here
            self._row_by_id[d["_id"]] = len(self._rows)
            self._ordered_ids.append(d["_id"])
            self._rows.append(vec)

    async def add(self, hypothesis_id: str, vec: np.ndarray) -> int:
        v = np.asarray(vec, dtype="float32").reshape(-1)
        doc = {
            "session_id": self.session_id,
            "model": self.cfg.embeddings.model,
            "embedding": [float(x) for x in v],
        }
        async with self._lock:
            await self.conn.coll(COLLECTION).update_one(
                {"_id": hypothesis_id},
                {"$set": doc, "$setOnInsert": {"created_at": datetime.now(UTC)}},
                upsert=True,
            )
            offset = len(self._ordered_ids)
            self._ordered_ids.append(hypothesis_id)
            self._rows.append(v)
            self._row_by_id[hypothesis_id] = offset
            self._added_at[hypothesis_id] = time.monotonic()
        return offset

    async def save(self) -> None:
        """No-op: every `add` is already durable."""

    async def search(self, vec: np.ndarray, k: int) -> list[tuple[str, float]]:
        if self.n == 0 or k <= 0:
            return []
        q = np.asarray(vec, dtype="float32").reshape(-1)
        best: dict[str, float] = {}
        try:
            for hid, cos in await self._index_hits(q, k):
                best[hid] = max(cos, best.get(hid, -2.0))
        except PyMongoError as e:
            # Missing/building index must never fail the agent; log the type only.
            get_logger("vectors.atlas").warning(
                "vector_search_fallback", error_type=type(e).__name__
            )
            candidates = list(self._row_by_id)
        else:
            now = time.monotonic()
            candidates = [h for h, t in self._added_at.items() if now - t <= RECENT_WINDOW_S]
        for hid in candidates:
            cos = float(self._rows[self._row_by_id[hid]] @ q)
            best[hid] = max(cos, best.get(hid, -2.0))
        return sorted(best.items(), key=lambda kv: kv[1], reverse=True)[:k]

    async def _index_hits(self, q: np.ndarray, k: int) -> list[tuple[str, float]]:
        pipeline = [
            {
                "$vectorSearch": {
                    "index": INDEX_NAME,
                    "path": "embedding",
                    "queryVector": [float(x) for x in q],
                    "numCandidates": max(100, 20 * k),
                    "limit": k,
                    "filter": {"session_id": self.session_id},
                }
            },
            {"$project": {"score": {"$meta": "vectorSearchScore"}}},
        ]
        cur = await self.conn.coll(COLLECTION).aggregate(pipeline)
        return [(d["_id"], vector_score_to_cosine(d["score"])) for d in await cur.to_list()]

    async def cosine_matrix(self) -> np.ndarray:
        if self.n == 0:
            return np.zeros((0, 0), dtype="float32")
        m = np.stack(self._rows)
        return m @ m.T

    def ids(self) -> list[str]:
        return list(self._ordered_ids)

    def similarity(self, a_id: str, b_id: str) -> float | None:
        i, j = self._row_by_id.get(a_id), self._row_by_id.get(b_id)
        if i is None or j is None:
            return None
        return float(self._rows[i] @ self._rows[j])
