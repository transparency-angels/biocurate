"""Tests for the FAISS store. Embedder is network-bound; we feed fake vectors."""

from __future__ import annotations

import numpy as np
import pytest

from co_scientist.vectors.store import FaissStore


def _vec(seed: int, dim: int = 8) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.normal(size=dim).astype("float32")
    return v / np.linalg.norm(v)


@pytest.mark.asyncio
async def test_faiss_store_add_search_persist(tmp_cfg) -> None:
    store = FaissStore(tmp_cfg, "ses_v", dim=8)
    await store.load_or_create()
    assert store.n == 0

    o1 = await store.add("hyp_1", _vec(1))
    o2 = await store.add("hyp_2", _vec(2))
    assert (o1, o2) == (0, 1)
    assert store.n == 2

    # k-NN should find itself first
    results = await store.search(_vec(1), k=2)
    assert results[0][0] == "hyp_1"
    assert results[0][1] == pytest.approx(1.0, abs=1e-3)

    # cosine matrix is 2x2 with 1s on diagonal
    m = await store.cosine_matrix()
    assert m.shape == (2, 2)
    assert m[0, 0] == pytest.approx(1.0, abs=1e-3)

    # Persist, then re-open
    await store.save()

    store2 = FaissStore(tmp_cfg, "ses_v", dim=8)
    await store2.load_or_create()
    assert store2.n == 2
    assert store2.hypothesis_at(0) == "hyp_1"
    assert store2.hypothesis_at(1) == "hyp_2"


@pytest.mark.asyncio
async def test_faiss_offset_lookup(tmp_cfg) -> None:
    store = FaissStore(tmp_cfg, "ses_v2", dim=4)
    await store.load_or_create()
    await store.add("a", _vec(1, 4))
    await store.add("b", _vec(2, 4))
    assert store.offset_of("a") == 0
    assert store.offset_of("b") == 1
    assert store.offset_of("missing") is None


@pytest.mark.asyncio
async def test_index_of_a_different_dim_is_rebuilt_not_reused(tmp_cfg) -> None:
    """Changing the embedding model invalidates the vectors already stored.

    Without the width check FAISS accepts the stale index and then fails deep
    inside `add` with an assertion that names nothing useful.
    """
    store = FaissStore(tmp_cfg, "ses_dim", dim=8)
    await store.load_or_create()
    await store.add("hyp_1", _vec(1, 8))
    await store.save()

    # Same session, wider embeddings — as after switching embedding model.
    reopened = FaissStore(tmp_cfg, "ses_dim", dim=16)
    await reopened.load_or_create()

    assert reopened.n == 0, "stale 8-d vectors must not survive into a 16-d index"
    assert reopened.index.d == 16
    assert reopened.offset_of("hyp_1") is None
    # And the fresh index is usable at the new width.
    await reopened.add("hyp_1", _vec(1, 16))
    assert reopened.n == 1


# ----------------------------- embedder fallback ----------------------------- #


@pytest.mark.asyncio
async def test_make_embedder_falls_back_to_hash_when_no_keys() -> None:
    """Without OPENAI_API_KEY, make_embedder should return HashEmbedder so
    dedup / proximity degrade rather than crash."""
    import os

    from co_scientist.config import Config
    from co_scientist.vectors.embedder import HashEmbedder, make_embedder

    cfg = Config()
    cfg.embeddings.provider = "openai"
    cfg.secrets.OPENAI_API_KEY = ""
    saved = os.environ.pop("OPENAI_API_KEY", None)
    try:
        emb = make_embedder(cfg)
    finally:
        if saved is not None:
            os.environ["OPENAI_API_KEY"] = saved
    assert isinstance(emb, HashEmbedder)


@pytest.mark.asyncio
async def test_hash_embedder_produces_normalized_unit_vectors() -> None:
    from co_scientist.config import Config
    from co_scientist.vectors.embedder import HashEmbedder

    cfg = Config()
    cfg.embeddings.dim = 128
    emb = HashEmbedder(cfg)
    vecs = await emb.embed(["microbiome inflammation hypothesis",
                            "tournament ranking hypothesis"])
    assert vecs.shape == (2, 128)
    # L2-normalized → ||v|| ≈ 1
    norms = np.linalg.norm(vecs, axis=1)
    assert all(abs(n - 1.0) < 1e-5 for n in norms)


@pytest.mark.asyncio
async def test_hash_embedder_similar_texts_have_higher_cosine() -> None:
    """The hash embedder is a bag-of-features stub, but near-duplicates of
    a text should still produce a higher cosine than unrelated text."""
    from co_scientist.config import Config
    from co_scientist.vectors.embedder import HashEmbedder

    cfg = Config()
    cfg.embeddings.dim = 1024
    emb = HashEmbedder(cfg)
    vecs = await emb.embed([
        "the gut microbiome drives chronic systemic inflammation",
        "the gut microbiome drives chronic systemic inflammation in humans",
        "quantum computing for solving prime factorization problems",
    ])
    sim_near = float(vecs[0] @ vecs[1])
    sim_far  = float(vecs[0] @ vecs[2])
    assert sim_near > sim_far


@pytest.mark.asyncio
async def test_openai_fallback_uses_large_at_the_configured_dim() -> None:
    """Falling back from another provider must not also downgrade the model.

    `embeddings.model` names a Voyage model here, so it cannot be forwarded to
    OpenAI. The fallback picks `-large` shortened to the configured dim, rather
    than `-small` at that dim — same vector width, better vectors, and existing
    FAISS indices stay valid because the dim is unchanged.
    """
    from co_scientist.config import Config
    from co_scientist.vectors.embedder import OpenAIEmbedder, make_embedder

    cfg = Config()                       # provider="voyage", dim=1024
    cfg.secrets.OPENAI_API_KEY = "sk-fake"
    emb = make_embedder(cfg)
    assert isinstance(emb, OpenAIEmbedder)
    assert emb.model == "text-embedding-3-large"
    assert emb.dim == cfg.embeddings.dim == 1024


@pytest.mark.asyncio
async def test_openai_as_the_configured_provider_honors_model_and_dim() -> None:
    """Choosing OpenAI outright forwards `embeddings.model` verbatim."""
    from co_scientist.config import Config
    from co_scientist.vectors.embedder import OpenAIEmbedder, make_embedder

    cfg = Config()
    cfg.embeddings.provider = "openai"
    cfg.embeddings.model = "text-embedding-3-large"
    cfg.embeddings.dim = 3072
    cfg.secrets.OPENAI_API_KEY = "sk-fake"
    emb = make_embedder(cfg)
    assert isinstance(emb, OpenAIEmbedder)
    assert emb.model == "text-embedding-3-large"
    assert emb.dim == 3072


def test_fallback_warning_emits_once_per_process() -> None:
    """Regression: ranking calls make_embedder() inside the pair-selection
    loop (potentially hundreds of times per session). The fallback warning
    must emit exactly once per process, not once per call.

    We probe the internal `_FALLBACK_WARNED` set rather than caplog because
    the project uses structlog, which doesn't always route through pytest's
    logging capture. The set is the source of truth for the once-per-process
    contract.
    """
    import os

    from co_scientist.config import Config
    from co_scientist.vectors import embedder as emb_mod

    emb_mod._reset_fallback_warned_for_tests()
    cfg = Config()
    cfg.embeddings.provider = "openai"
    cfg.secrets.OPENAI_API_KEY = ""
    saved = os.environ.pop("OPENAI_API_KEY", None)
    try:
        for _ in range(50):
            emb_mod.make_embedder(cfg)
    finally:
        if saved is not None:
            os.environ["OPENAI_API_KEY"] = saved

    # Exactly one warning marker recorded; subsequent calls hit the cache.
    assert {"openai_key_missing_using_hash_fallback"} == emb_mod._FALLBACK_WARNED


@pytest.mark.asyncio
async def test_faiss_store_similarity_matches_dot(tmp_cfg) -> None:
    store = FaissStore(tmp_cfg, "ses_sim", dim=8)
    await store.load_or_create()
    va, vb = _vec(1), _vec(2)
    await store.add("hyp_a", va)
    await store.add("hyp_b", vb)
    assert store.similarity("hyp_a", "hyp_b") == pytest.approx(float(va @ vb))
    assert store.similarity("hyp_a", "nope") is None
    assert store.similarity("nope", "hyp_b") is None
    assert store.ids() == ["hyp_a", "hyp_b"]


@pytest.mark.asyncio
async def test_faiss_store_satisfies_protocol(tmp_cfg) -> None:
    import inspect

    from co_scientist.vectors.base import VectorStore

    store = FaissStore(tmp_cfg, "ses_proto", dim=8)
    assert isinstance(store, VectorStore)
    # runtime_checkable only checks member presence; check async-ness too.
    for name in ("load_or_create", "add", "save", "search", "cosine_matrix"):
        assert inspect.iscoroutinefunction(getattr(store, name)), name
        assert inspect.iscoroutinefunction(getattr(VectorStore, name)), name
    for name in ("ids", "similarity"):
        assert not inspect.iscoroutinefunction(getattr(store, name)), name


@pytest.mark.asyncio
async def test_make_vector_store_defaults_to_faiss(tmp_cfg, conn) -> None:
    from co_scientist.vectors.factory import make_vector_store

    store = make_vector_store(tmp_cfg, conn, "ses_fac", dim=8)
    assert isinstance(store, FaissStore)
    assert store.dim == 8


# ----------------------------- Atlas store (offline) ----------------------------- #

import time  # noqa: E402

from pymongo.errors import OperationFailure  # noqa: E402

from co_scientist.config import Config  # noqa: E402
from co_scientist.storage.atlas import indexes as _idx  # noqa: E402
from co_scientist.storage.atlas.client import AtlasConn  # noqa: E402
from co_scientist.vectors import atlas_store as AS  # noqa: E402
from co_scientist.vectors.atlas_store import AtlasVectorStore, vector_score_to_cosine  # noqa: E402
from co_scientist.vectors.factory import make_vector_store  # noqa: E402


def test_vector_score_to_cosine() -> None:
    assert vector_score_to_cosine(1.0) == pytest.approx(1.0)
    assert vector_score_to_cosine(0.5) == pytest.approx(0.0)
    assert vector_score_to_cosine(0.96) == pytest.approx(0.92)


class _Cur:
    def __init__(self, rows):
        self.rows = rows

    async def to_list(self, length=None):
        return list(self.rows)


class _FakeVecColl:
    def __init__(self, hits=None, error=None, docs=None):
        self.hits, self.error, self.docs = hits or [], error, docs or []
        self.pipelines: list = []
        self.upserts: list = []

    def find(self, *a, **kw):
        return _Cur(self.docs)

    async def update_one(self, flt, upd, upsert=False):
        self.upserts.append((flt, upd, upsert))

    async def aggregate(self, pipeline):
        self.pipelines.append(pipeline)
        if self.error is not None:
            raise self.error
        return _Cur(self.hits)


class _FakeVecConn:
    def __init__(self, coll):
        self.c = coll

    def coll(self, name):
        assert name == "hypothesis_vectors"
        return self.c


def _unit(dim: int, *xs: float) -> np.ndarray:
    v = np.zeros(dim, dtype="float32")
    v[: len(xs)] = xs
    return v / np.linalg.norm(v)


async def _store(coll, dim: int = 4) -> AtlasVectorStore:
    s = AtlasVectorStore(Config(), _FakeVecConn(coll), "s1", dim)
    await s.load_or_create()
    return s


async def test_atlas_store_empty_and_unknown() -> None:
    s = await _store(_FakeVecColl())
    assert s.n == 0 and s.ids() == []
    assert await s.search(_unit(4, 1), 3) == []
    assert (await s.cosine_matrix()).shape == (0, 0)
    assert s.similarity("a", "b") is None


async def test_atlas_store_add_returns_ordinal_and_bson_floats() -> None:
    coll = _FakeVecColl()
    s = await _store(coll)
    assert await s.add("a", _unit(4, 1)) == 0
    assert await s.add("b", _unit(4, 0, 1)) == 1
    emb = coll.upserts[0][1]["$set"]["embedding"]
    assert type(emb) is list and type(emb[0]) is float
    assert s.similarity("a", "b") == pytest.approx(0.0)
    assert s.similarity("a", "zzz") is None
    m = await s.cosine_matrix()
    assert m.shape == (2, 2) and s.ids() == ["a", "b"]
    await s.save()


async def test_atlas_store_readd_appends_like_faiss(tmp_cfg) -> None:
    f = FaissStore(tmp_cfg, "rd", dim=4)
    await f.load_or_create()
    s = await _store(_FakeVecColl())
    for st in (f, s):
        await st.add("a", _unit(4, 1))
        await st.add("b", _unit(4, 0, 1))
        assert await st.add("a", _unit(4, 1, 1)) == 2
    assert f.n == s.n == 3 and f.ids() == s.ids() == ["a", "b", "a"]
    assert s.similarity("a", "b") == pytest.approx(f.similarity("a", "b"), abs=1e-6)


async def test_atlas_store_search_merges_recent_and_dedupes(monkeypatch) -> None:
    hits = [{"_id": "old", "score": 0.99}, {"_id": "dup", "score": 0.6}]
    coll = _FakeVecColl(hits=hits)
    s = await _store(coll)
    await s.add("fresh", _unit(4, 1))  # recent, not yet in the index
    await s.add("dup", _unit(4, 1))
    res = await s.search(_unit(4, 1), 5)
    d = dict(res)
    assert d["old"] == pytest.approx(0.98)
    assert d["fresh"] == pytest.approx(1.0)
    assert d["dup"] == pytest.approx(1.0)  # max of index 0.2 and exact 1.0
    assert [i for i, _ in res].count("dup") == 1
    assert [c for _, c in res] == sorted((c for _, c in res), reverse=True)
    assert len(await s.search(_unit(4, 1), 2)) == 2
    pipe = coll.pipelines[0][0]["$vectorSearch"]
    assert pipe["index"] == "hyp_vec" and pipe["filter"] == {"session_id": "s1"}
    assert pipe["numCandidates"] == 100


async def test_atlas_store_search_exact_when_index_returns_nothing(monkeypatch) -> None:
    s = await _store(_FakeVecColl(hits=[]))
    for name, x in (("a", (1, 1)), ("b", (0, 1)), ("c", (0, 0, 1))):
        await s.add(name, _unit(4, *x))
    real = time.monotonic
    monkeypatch.setattr(AS.time, "monotonic", lambda: real() + 3600)  # all "old"
    res = await s.search(_unit(4, 1, 1), 1)
    assert res[0][0] == "a" and res[0][1] == pytest.approx(1.0)


async def test_atlas_store_search_trusts_full_index_results(monkeypatch) -> None:
    s = await _store(_FakeVecColl(hits=[{"_id": "x", "score": 0.9}, {"_id": "y", "score": 0.7}]))
    await s.add("a", _unit(4, 1))
    await s.add("b", _unit(4, 0, 1))
    calls: list = []
    monkeypatch.setattr(s, "_exact", lambda *a: calls.append(a) or [])
    real = time.monotonic
    monkeypatch.setattr(AS.time, "monotonic", lambda: real() + 3600)
    res = await s.search(_unit(4, 1), 2)
    assert calls == [] and [i for i, _ in res] == ["x", "y"]


async def test_atlas_store_load_handles_missing_and_aware_created_at() -> None:
    from datetime import UTC, datetime

    docs = [
        {"_id": "b", "embedding": [0, 1.0, 0, 0], "created_at": datetime(2026, 1, 1, tzinfo=UTC)},
        {"_id": "n", "embedding": [0, 0, 1.0, 0]},
        {"_id": "a", "embedding": [1.0, 0, 0, 0], "created_at": datetime(2026, 1, 2)},
    ]
    s = await _store(_FakeVecColl(docs=docs))
    assert s.ids() == ["n", "b", "a"]


async def test_atlas_store_search_falls_back_on_pymongo_error() -> None:
    err = OperationFailure("cannot query search index while in state INITIAL_SYNC", code=8)
    s = await _store(_FakeVecColl(error=err))
    await s.add("a", _unit(4, 1))
    await s.add("b", _unit(4, 0, 1))
    res = await s.search(_unit(4, 1), 5)
    assert [i for i, _ in res] == ["a", "b"]
    assert res[0][1] == pytest.approx(1.0) and res[1][1] == pytest.approx(0.0)
    assert AS.RECENT_WINDOW_S == 30.0


async def test_atlas_store_loads_existing_session_vectors() -> None:
    docs = [{"_id": "a", "embedding": [1.0, 0, 0, 0]}, {"_id": "b", "embedding": [0, 1.0, 0, 0]}]
    s = await _store(_FakeVecColl(docs=docs))
    assert s.n == 2 and s.ids() == ["a", "b"]
    assert await s.add("c", _unit(4, 1)) == 2


def test_hyp_vec_definition_and_registration() -> None:
    cfg = Config()
    assert _idx.hyp_vec_definition(cfg) == {
        "fields": [
            {"type": "vector", "path": "embedding", "numDimensions": cfg.embeddings.dim,
             "similarity": "dotProduct"},
            {"type": "filter", "path": "session_id"},
        ]
    }
    spec = [s for s in _idx.SEARCH_INDEX_SPECS if s.collection == "hypothesis_vectors"]
    assert [(s.name, s.type) for s in spec] == [("hyp_vec", "vectorSearch")]
    assert [m.document["name"] for m in _idx.BTREE_INDEXES["hypothesis_vectors"]] == ["hv_sess"]


def test_factory_atlas_branch_returns_atlas_store() -> None:
    conn = AtlasConn(client=None, db=None, prefix="t_")
    s = make_vector_store(Config(), conn, "s1", 8)
    assert isinstance(s, AtlasVectorStore)
