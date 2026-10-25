from __future__ import annotations

import pytest

from co_scientist.config import Config, LibraryCfg
from co_scientist.library.search import LibraryHit, build_hybrid_pipeline, rerank, rrf


def _hit(i: int) -> LibraryHit:
    return LibraryHit(
        f"PMC1#p{i}", "PMC1", "T", "Results", "paragraph", None, f"text {i}",
        "u", 0.5, None,
    )


def test_build_hybrid_pipeline_first_stage_is_rankfusion() -> None:
    p = build_hybrid_pipeline(Config(), "trem2", k=8)
    assert list(p[0]) == ["$rankFusion"]
    rf = p[0]["$rankFusion"]
    pipes = rf["input"]["pipelines"]
    assert set(pipes) == {"text", "vector"}
    assert rf["combination"]["weights"] == {"text": 1, "vector": 1}
    vs = pipes["vector"][0]["$vectorSearch"]
    assert vs["query"] == {"text": "trem2"}
    assert vs["index"] == "library_vec" and vs["limit"] == 32 and vs["numCandidates"] == 160
    assert pipes["text"][0]["$search"]["index"] == "library_text"
    assert {"$limit": 32} in pipes["text"]
    assert {"$limit": 32} in p[1:]
    assert p[-1]["$project"]["fused_score"] == {"$meta": "score"}


def test_build_hybrid_pipeline_kind_filter() -> None:
    p = build_hybrid_pipeline(Config(), "q", k=4, kind="figure")
    pipes = p[0]["$rankFusion"]["input"]["pipelines"]
    assert pipes["vector"][0]["$vectorSearch"]["filter"] == {"kind": "figure"}
    comp = pipes["text"][0]["$search"]["compound"]
    assert comp["filter"] == [{"equals": {"path": "kind", "value": "figure"}}]
    assert comp["must"][0]["text"]["query"] == "q"


def test_build_hybrid_pipeline_client_mode_uses_query_vector() -> None:
    cfg = Config(library=LibraryCfg(embedding="client"))
    p = build_hybrid_pipeline(cfg, "q", k=2, query_vector=[0.1, 0.2])
    vs = p[0]["$rankFusion"]["input"]["pipelines"]["vector"][0]["$vectorSearch"]
    assert vs["queryVector"] == [0.1, 0.2] and "query" not in vs
    assert vs["path"] == "embedding"


def test_rrf_orders_by_reciprocal_rank() -> None:
    out = rrf([["a", "b"], ["b", "c"]])
    assert out[0][0] == "b"
    assert [x for x, _ in out] == ["b", "a", "c"]


async def test_rerank_without_key_passes_through() -> None:
    hits = [_hit(i) for i in range(5)]
    out = await rerank(Config(), "q", hits, 3)
    assert [h.anchor_id for h in out] == [h.anchor_id for h in hits[:3]]
    assert all(h.rerank_score is None for h in out)


def _keyed_cfg() -> Config:
    cfg = Config()
    cfg.secrets.VOYAGE_API_KEY = "sk-super-secret"
    return cfg


async def test_rerank_maps_results_by_index(monkeypatch) -> None:
    import types

    import voyageai

    class FakeClient:
        def __init__(self, api_key=None):
            pass

        def rerank(self, query, documents, model, top_k):
            r = [types.SimpleNamespace(index=2, relevance_score=0.9),
                 types.SimpleNamespace(index=0, relevance_score=0.4)]
            return types.SimpleNamespace(results=r)

    monkeypatch.setattr(voyageai, "Client", FakeClient)
    hits = [_hit(0), _hit(1), _hit(2)]
    out = await rerank(_keyed_cfg(), "q", hits, 2)
    assert [(h.anchor_id, h.rerank_score) for h in out] == [("PMC1#p2", 0.9), ("PMC1#p0", 0.4)]


async def test_rerank_failure_passes_through(monkeypatch) -> None:
    import voyageai
    from structlog.testing import capture_logs

    class FakeClient:
        def __init__(self, api_key=None):
            pass

        def rerank(self, *a, **kw):
            raise RuntimeError("429 for key sk-super-secret")

    monkeypatch.setattr(voyageai, "Client", FakeClient)
    hits = [_hit(0), _hit(1), _hit(2)]
    with capture_logs() as logs:
        out = await rerank(_keyed_cfg(), "q", hits, 2)
    assert [h.anchor_id for h in out] == ["PMC1#p0", "PMC1#p1"]
    assert all(h.rerank_score is None for h in out)
    assert logs and "sk-super-secret" not in str(logs)


def _scope(cfg=None, **kw):
    p = build_hybrid_pipeline(cfg or Config(), "q", k=4, scoped=True, **kw)
    pipes = p[0]["$rankFusion"]["input"]["pipelines"]
    return pipes["text"][0]["$search"], pipes["vector"][0]["$vectorSearch"]


def test_build_hybrid_pipeline_session_scope_filter() -> None:
    search, vec = _scope(session_id="S1")
    assert search["index"] == "library_text_v2" and vec["index"] == "library_vec_v2"
    assert vec["filter"] == {"$or": [{"source": {"$ne": "upload"}}, {"session_id": "S1"}]}
    mn = search["compound"]["mustNot"]
    assert mn == [
        {
            "compound": {
                "must": [{"equals": {"path": "source", "value": "upload"}}],
                "mustNot": [{"equals": {"path": "session_id", "value": "S1"}}],
            }
        }
    ]
    assert search["compound"]["must"][0]["text"]["query"] == "q"


def test_build_hybrid_pipeline_scope_without_session_and_with_kind() -> None:
    search, vec = _scope()
    assert vec["filter"] == {"source": {"$ne": "upload"}}
    assert search["compound"]["mustNot"] == [{"equals": {"path": "source", "value": "upload"}}]
    search, vec = _scope(session_id="S1", kind="figure")
    assert vec["filter"] == {
        "$and": [
            {"kind": "figure"},
            {"$or": [{"source": {"$ne": "upload"}}, {"session_id": "S1"}]},
        ]
    }
    assert search["compound"]["filter"] == [{"equals": {"path": "kind", "value": "figure"}}]


def test_unscoped_pipeline_uses_v1_without_filter() -> None:
    p = build_hybrid_pipeline(Config(), "q", k=4, session_id="S1")
    pipes = p[0]["$rankFusion"]["input"]["pipelines"]
    assert pipes["vector"][0]["$vectorSearch"]["index"] == "library_vec"
    assert "filter" not in pipes["vector"][0]["$vectorSearch"]
    assert pipes["text"][0]["$search"]["index"] == "library_text"
    assert "compound" not in pipes["text"][0]["$search"]


def _doc(i, source=None, sid=None):
    d = {"_id": f"a{i}", "text": "t", "fused_score": 1.0}
    if source:
        d["source"] = source
    if sid:
        d["session_id"] = sid
    return d


class _Cur:
    def __init__(self, docs):
        self.docs = docs

    async def to_list(self):
        return self.docs


class _Coll:
    def __init__(self, docs, indexes):
        self.docs, self.indexes, self.pipelines = docs, indexes, []

    async def aggregate(self, pipeline):
        self.pipelines.append(pipeline)
        return _Cur(self.docs)

    async def list_search_indexes(self, name=None):
        return _Cur([{"name": n, "queryable": q} for n, q in self.indexes.items()])


class _Conn:
    def __init__(self, coll, prefix="p_"):
        self._c, self.prefix = coll, prefix

        class _Db:
            name = "db"

        self.db = _Db()

    def coll(self, name):
        return self._c


async def test_hybrid_search_falls_back_to_v1_and_filters_in_python() -> None:
    from co_scientist.library import search

    search._SCOPED_READY.clear()
    docs = [
        _doc(1), _doc(2, "europepmc"), _doc(3, "upload", "OTHER"),
        _doc(4, "upload", "S1"), _doc(5, "upload", "OTHER"),
    ]
    coll = _Coll(docs, {"library_text_v2": True, "library_vec_v2": False})
    hits = await search.hybrid_search(_Conn(coll), Config(), "q", k=3, session_id="S1")
    assert [h.anchor_id for h in hits] == ["a1", "a2", "a4"]
    pipe = coll.pipelines[0]
    vs = pipe[0]["$rankFusion"]["input"]["pipelines"]["vector"][0]["$vectorSearch"]
    assert vs["index"] == "library_vec" and "filter" not in vs
    assert vs["limit"] == 4 * 3 * 2  # over-fetched


async def test_hybrid_search_uses_v2_when_both_queryable_and_caches() -> None:
    from co_scientist.library import search

    search._SCOPED_READY.clear()
    coll = _Coll([_doc(1)], {"library_text_v2": True, "library_vec_v2": True})
    conn = _Conn(coll)
    for _ in range(2):
        await search.hybrid_search(conn, Config(), "q", k=3, session_id="S1")
    vs = coll.pipelines[0][0]["$rankFusion"]["input"]["pipelines"]["vector"][0]["$vectorSearch"]
    assert vs["index"] == "library_vec_v2" and "filter" in vs
    assert coll.pipelines[1] == coll.pipelines[0]
    assert len(search._SCOPED_READY) == 1


@pytest.fixture(autouse=True)
def _clear_scoped_ready():
    from co_scientist.library import search

    search._SCOPED_READY.clear()
    yield
    search._SCOPED_READY.clear()


async def test_scoped_ready_false_is_rechecked_after_ttl(monkeypatch) -> None:
    from co_scientist.library import search

    now = [1000.0]
    monkeypatch.setattr(search.time, "monotonic", lambda: now[0])
    idx = {"library_text_v2": True, "library_vec_v2": False}
    calls = []
    coll = _Coll([], idx)
    orig = coll.list_search_indexes

    async def counting(name=None):
        calls.append(1)
        return await orig(name)

    coll.list_search_indexes = counting
    conn = _Conn(coll)
    assert await search.scoped_indexes_ready(conn, Config()) is False
    idx["library_vec_v2"] = True
    now[0] += search._NOT_READY_TTL_S - 1
    assert await search.scoped_indexes_ready(conn, Config()) is False
    assert len(calls) == 1
    now[0] += 2
    assert await search.scoped_indexes_ready(conn, Config()) is True
    assert len(calls) == 2
    now[0] += 10_000  # True is cached for good
    assert await search.scoped_indexes_ready(conn, Config()) is True
    assert len(calls) == 2
