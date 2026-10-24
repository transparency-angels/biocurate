from __future__ import annotations

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
