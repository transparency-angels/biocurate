from __future__ import annotations

import asyncio

import numpy as np
import pytest

from co_scientist.storage.atlas.indexes import wait_for_search_index
from co_scientist.vectors.atlas_store import AtlasVectorStore

pytestmark = pytest.mark.atlas_search


def _unit(dim: int, *xs: float) -> np.ndarray:
    v = np.zeros(dim, dtype="float32")
    v[: len(xs)] = xs
    return v / np.linalg.norm(v)


async def _store(conn, cfg, session: str) -> AtlasVectorStore:
    s = AtlasVectorStore(cfg, conn, session, cfg.embeddings.dim)
    await s.load_or_create()
    return s


async def test_atlas_vector_search_returns_cosine(atlas_conn, atlas_cfg):
    dim = atlas_cfg.embeddings.dim
    s = await _store(atlas_conn, atlas_cfg, "sA")
    await s.add("same", _unit(dim, 1))
    await s.add("orth", _unit(dim, 0, 1))
    coll = atlas_conn.coll("hypothesis_vectors")
    assert await wait_for_search_index(coll, "hyp_vec", timeout_s=900, poll_s=10)
    # A fresh instance has no recent in-memory vectors, so hits come from the index.
    s2 = await _store(atlas_conn, atlas_cfg, "sA")
    got: dict[str, float] = {}
    for _ in range(30):
        got = dict(await s2._index_hits(_unit(dim, 1), 5))
        if len(got) == 2:
            break
        await asyncio.sleep(10)
    assert got["same"] == pytest.approx(1.0, abs=1e-3)
    assert got["orth"] == pytest.approx(0.0, abs=1e-3)
    res = dict(await s2.search(_unit(dim, 1), 5))
    assert res["same"] == pytest.approx(1.0, abs=1e-3)


async def test_atlas_vector_search_sees_just_added_vector(atlas_conn, atlas_cfg):
    dim = atlas_cfg.embeddings.dim
    s = await _store(atlas_conn, atlas_cfg, "sA")
    await s.add("fresh", _unit(dim, 1, 1))
    # The real scenario is another worker: a fresh instance, seeded from `updated_at`.
    other = await _store(atlas_conn, atlas_cfg, "sA")
    res = await other.search(_unit(dim, 1, 1), 3)
    assert res[0][0] == "fresh"
    assert res[0][1] == pytest.approx(1.0, abs=1e-3)


async def test_atlas_store_scoped_to_session(atlas_conn, atlas_cfg):
    dim = atlas_cfg.embeddings.dim
    a = await _store(atlas_conn, atlas_cfg, "sA")
    b = await _store(atlas_conn, atlas_cfg, "sB")
    await b.add("only_b", _unit(dim, 1))
    await a.add("only_a", _unit(dim, 0, 1))
    coll = atlas_conn.coll("hypothesis_vectors")
    assert await wait_for_search_index(coll, "hyp_vec", timeout_s=900, poll_s=10)
    a2 = await _store(atlas_conn, atlas_cfg, "sA")
    assert a2.ids() == ["only_a"]
    for _ in range(20):
        hits = await a2._index_hits(_unit(dim, 1), 5)
        if hits:
            break
        await asyncio.sleep(10)
    assert [h for h, _ in hits] == ["only_a"]
    assert "only_b" not in [h for h, _ in await a2.search(_unit(dim, 1), 5)]
