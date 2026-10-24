"""Backend-neutral vector store contract used by the agents."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np


@runtime_checkable
class VectorStore(Protocol):
    """Per-session hypothesis embedding index (cosine similarity)."""

    @property
    def n(self) -> int: ...

    async def load_or_create(self) -> None: ...

    async def add(self, hypothesis_id: str, vec: np.ndarray) -> int: ...

    async def save(self) -> None: ...

    async def search(self, vec: np.ndarray, k: int) -> list[tuple[str, float]]:
        """Best matches as (hypothesis_id, cosine), descending."""
        ...

    async def cosine_matrix(self) -> np.ndarray:
        """N x N cosine matrix; rows follow `ids()`."""
        ...

    def ids(self) -> list[str]:
        """Hypothesis ids in `cosine_matrix` row order."""
        ...

    def similarity(self, a_id: str, b_id: str) -> float | None:
        """Cosine between two stored hypotheses, or None if either is unknown."""
        ...
