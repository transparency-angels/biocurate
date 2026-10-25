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
    source: str = ""
    session_id: str | None = None


def rrf(lists: list[list[str]], k: int = 60) -> list[tuple[str, float]]:
    """Reciprocal-rank fusion of ranked id lists; best first."""
    scores: dict[str, float] = {}
    for ranked in lists:
        for rank, key in enumerate(ranked, start=1):
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)


def _text_scope(session_id: str | None) -> dict:
    """`$search` clause hiding other sessions' uploads; passages with no `source` stay visible."""
    upload = {"equals": {"path": "source", "value": "upload"}}
    if session_id is None:
        return upload
    own = {"equals": {"path": "session_id", "value": session_id}}
    return {"compound": {"must": [upload], "mustNot": [own]}}


def _vector_scope(session_id: str | None) -> dict:
    not_upload = {"source": {"$ne": "upload"}}
    if session_id is None:
        return not_upload
    return {"$or": [not_upload, {"session_id": session_id}]}


def build_hybrid_pipeline(
    cfg: Config,
    query: str,
    *,
    k: int,
    kind: str | None = None,
    query_vector: list[float] | None = None,
    session_id: str | None = None,
    scoped: bool = False,
) -> list[dict]:
    """One `$rankFusion` over a `$search` branch and a `$vectorSearch` branch.

    `scoped` selects the v2 indexes and filters both branches to the Europe PMC passages plus
    `session_id`'s own uploads (none when `session_id` is None). Otherwise the v1 indexes are
    used unfiltered and the caller must drop other sessions' uploads itself.
    """
    lib = cfg.library
    n = 4 * k
    text_op: dict = {"text": {"query": query, "path": ["text", "title"]}}
    text_index = lib.scoped_search_index if scoped else lib.search_index
    vector_index = lib.scoped_vector_index if scoped else lib.vector_index
    if kind or scoped:
        compound: dict = {"must": [text_op]}
        if kind:
            compound["filter"] = [{"equals": {"path": "kind", "value": kind}}]
        if scoped:
            compound["mustNot"] = [_text_scope(session_id)]
        search = {"index": text_index, "compound": compound}
    else:
        search = {"index": text_index, **text_op}
    vector: dict = {"index": vector_index, "numCandidates": 20 * k, "limit": n}
    if lib.embedding == "auto":
        vector["path"] = "text"
        vector["query"] = {"text": query}
    else:
        if query_vector is None:
            raise ValueError("client embedding mode needs query_vector")
        vector["path"] = "embedding"
        vector["queryVector"] = query_vector
    vfilters = ([{"kind": kind}] if kind else []) + (
        [_vector_scope(session_id)] if scoped else []
    )
    if len(vfilters) == 1:
        vector["filter"] = vfilters[0]
    elif vfilters:
        vector["filter"] = {"$and": vfilters}
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
                "text": 1, "url": 1, "source": 1, "session_id": 1,
                "fused_score": {"$meta": "score"},
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
        source=doc.get("source", ""),
        session_id=doc.get("session_id"),
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


# (db name, collection prefix) -> whether both v2 indexes were queryable when first checked.
_SCOPED_READY: dict[tuple[str, str], bool] = {}


async def scoped_indexes_ready(conn: AtlasConn, cfg: Config) -> bool:
    """True once both v2 indexes are queryable; checked once per process per connection prefix."""
    key = (conn.db.name, conn.prefix)
    if key not in _SCOPED_READY:
        lib = cfg.library
        cur = await conn.coll("library").list_search_indexes()
        ready = {d["name"] for d in await cur.to_list() if d.get("queryable")}
        _SCOPED_READY[key] = {lib.scoped_search_index, lib.scoped_vector_index} <= ready
    return _SCOPED_READY[key]


def _visible(hit: LibraryHit, session_id: str | None) -> bool:
    return hit.source != "upload" or (session_id is not None and hit.session_id == session_id)


async def hybrid_search(
    conn: AtlasConn,
    cfg: Config,
    query: str,
    *,
    k: int = 8,
    kind: str | None = None,
    session_id: str | None = None,
) -> list[LibraryHit]:
    """Hybrid search over Europe PMC passages plus `session_id`'s own uploads.

    With the v2 indexes queryable the scope is a server-side filter. Until then the v1 indexes
    are queried unfiltered (over-fetching) and other sessions' uploads are dropped here.
    """
    if k < 1:
        raise ValueError("k must be >= 1")
    qvec = None
    if cfg.library.embedding == "client":
        from ..vectors.embedder import make_embedder

        qvec = [float(x) for x in (await make_embedder(cfg).embed([query]))[0]]
    scoped = await scoped_indexes_ready(conn, cfg)
    pipeline = build_hybrid_pipeline(
        cfg, query, k=k if scoped else 2 * k, kind=kind, query_vector=qvec,
        session_id=session_id, scoped=scoped,
    )
    cur = await conn.coll("library").aggregate(pipeline)
    hits = [_to_hit(d) for d in await cur.to_list()]
    if not scoped:
        hits = [h for h in hits if _visible(h, session_id)]
    return await rerank(cfg, query, hits, k)
