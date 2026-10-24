"""Hybrid retrieval over the evidence library: `$rankFusion` + Voyage rerank."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from ..logging import get_logger

if TYPE_CHECKING:
    from ..config import Config
    from ..storage.atlas.client import AtlasConn

log = get_logger(__name__)


@dataclass
class LibraryHit:
    anchor_id: str
    pmcid: str
    title: str
    section: str
    kind: str
    label: str | None
    text: str
    url: str
    fused_score: float
    rerank_score: float | None = None


def rrf(lists: list[list[str]], k: int = 60) -> list[tuple[str, float]]:
    """Reciprocal-rank fusion of ranked id lists; best first."""
    scores: dict[str, float] = {}
    for ranked in lists:
        for rank, key in enumerate(ranked, start=1):
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)


def build_hybrid_pipeline(
    cfg: Config,
    query: str,
    *,
    k: int,
    kind: str | None = None,
    query_vector: list[float] | None = None,
) -> list[dict]:
    """One `$rankFusion` over a `$search` branch and a `$vectorSearch` branch."""
    lib = cfg.library
    n = 4 * k
    text_op: dict = {"text": {"query": query, "path": ["text", "title"]}}
    if kind:
        search = {
            "index": lib.search_index,
            "compound": {
                "must": [text_op],
                "filter": [{"equals": {"path": "kind", "value": kind}}],
            },
        }
    else:
        search = {"index": lib.search_index, **text_op}
    vector: dict = {"index": lib.vector_index, "numCandidates": 20 * k, "limit": n}
    if lib.embedding == "auto":
        vector["path"] = "text"
        vector["query"] = {"text": query}
    else:
        if query_vector is None:
            raise ValueError("client embedding mode needs query_vector")
        vector["path"] = "embedding"
        vector["queryVector"] = query_vector
    if kind:
        vector["filter"] = {"kind": kind}
    return [
        {
            "$rankFusion": {
                "input": {
                    "pipelines": {
                        "text": [{"$search": search}, {"$limit": n}],
                        "vector": [{"$vectorSearch": vector}],
                    }
                },
                "combination": {"weights": {"text": 1, "vector": 1}},
            }
        },
        {"$limit": n},
        {
            "$project": {
                "_id": 1, "pmcid": 1, "title": 1, "section": 1, "kind": 1, "label": 1,
                "text": 1, "url": 1, "fused_score": {"$meta": "score"},
            }
        },
    ]


def _to_hit(doc: dict) -> LibraryHit:
    return LibraryHit(
        anchor_id=doc["_id"],
        pmcid=doc.get("pmcid", ""),
        title=doc.get("title", ""),
        section=doc.get("section", ""),
        kind=doc.get("kind", ""),
        label=doc.get("label"),
        text=doc.get("text", ""),
        url=doc.get("url", ""),
        fused_score=float(doc.get("fused_score") or 0.0),
    )


async def rerank(cfg: Config, query: str, hits: list[LibraryHit], top_k: int) -> list[LibraryHit]:
    """Voyage rerank; passes `hits[:top_k]` through unscored without a key or on error."""
    if not hits:
        return []
    api_key = cfg.secrets.VOYAGE_API_KEY or os.environ.get("VOYAGE_API_KEY")
    if not api_key:
        return hits[:top_k]
    try:
        import voyageai

        # Sync client off-thread, as in vectors/embedder.py: AsyncClient (aiohttp) fails TLS
        # verification on interpreters without the system CA bundle; `requests` uses certifi.
        client = voyageai.Client(api_key=api_key)
        res = await asyncio.to_thread(
            client.rerank, query, [h.text for h in hits],
            model=cfg.library.rerank_model, top_k=top_k,
        )
        return [
            replace(hits[r.index], rerank_score=float(r.relevance_score)) for r in res.results
        ]
    except Exception as e:  # network, 429, bad response: degrade to fused order
        log.warning("library_rerank_failed", error=type(e).__name__)
        return hits[:top_k]


async def hybrid_search(
    conn: AtlasConn, cfg: Config, query: str, *, k: int = 8, kind: str | None = None
) -> list[LibraryHit]:
    if k < 1:
        raise ValueError("k must be >= 1")
    qvec = None
    if cfg.library.embedding == "client":
        from ..vectors.embedder import make_embedder

        qvec = [float(x) for x in (await make_embedder(cfg).embed([query]))[0]]
    pipeline = build_hybrid_pipeline(cfg, query, k=k, kind=kind, query_vector=qvec)
    cur = await conn.coll("library").aggregate(pipeline)
    hits = [_to_hit(d) for d in await cur.to_list()]
    return await rerank(cfg, query, hits, k)
