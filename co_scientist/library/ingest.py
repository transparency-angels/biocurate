"""Ingest Europe PMC open-access full text into the Atlas evidence library."""

from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Protocol

import httpx

from ..logging import get_logger
from ..storage.atlas import library as lib_store
from ..vectors.embedder import make_embedder
from .fetch import fetch_jats, make_client, search_oa_pmcids
from .jats import PaperMeta, Passage, parse_jats

if TYPE_CHECKING:
    from ..config import Config
    from ..storage.atlas.client import AtlasConn

log = get_logger(__name__)

_CONCURRENCY = 4


class LibraryStore(Protocol):
    async def has_paper(self, pmcid: str) -> bool: ...

    async def upsert_passages(
        self,
        meta: PaperMeta,
        passages: list[Passage],
        *,
        embeddings: list[list[float]] | None = None,
    ) -> int: ...


class AtlasLibraryStore:
    """`LibraryStore` over the Atlas module functions, with the connection captured."""

    def __init__(self, conn: AtlasConn) -> None:
        self._conn = conn

    async def has_paper(self, pmcid: str) -> bool:
        return await lib_store.has_paper(self._conn, pmcid)

    async def upsert_passages(
        self,
        meta: PaperMeta,
        passages: list[Passage],
        *,
        embeddings: list[list[float]] | None = None,
    ) -> int:
        return await lib_store.upsert_passages(self._conn, meta, passages, embeddings=embeddings)


@dataclass
class IngestReport:
    papers: int = 0
    passages: int = 0
    skipped: list[str] = field(default_factory=list)
    already_present: list[str] = field(default_factory=list)


def dedupe_anchors(passages: list[Passage]) -> list[Passage]:
    """Suffix repeated anchors with `~2`, `~3`, ... so `_id`s stay unique per paper."""
    seen: Counter[str] = Counter()
    out: list[Passage] = []
    for p in passages:
        seen[p.anchor_id] += 1
        n = seen[p.anchor_id]
        out.append(p if n == 1 else replace(p, anchor_id=f"{p.anchor_id}~{n}"))
    return out


async def ingest_query(
    conn: AtlasConn | None,
    cfg: Config,
    query: str,
    *,
    max_papers: int = 10,
    http: httpx.AsyncClient | None = None,
    store: LibraryStore | None = None,
) -> IngestReport:
    """Search Europe PMC for OA papers, parse their JATS and upsert the passages."""
    if store is None:
        if conn is None:
            raise ValueError("either conn or store is required")
        store = AtlasLibraryStore(conn)
    own_http = http is None
    client = http or make_client()
    embedder = make_embedder(cfg) if cfg.library.embedding == "client" else None
    report = IngestReport()
    sem = asyncio.Semaphore(_CONCURRENCY)

    async def one(pmcid: str) -> None:
        async with sem:
            if await store.has_paper(pmcid):
                report.already_present.append(pmcid)
                return
            try:
                xml = await fetch_jats(client, pmcid)
            except httpx.HTTPError as e:
                log.warning("library_fetch_failed", pmcid=pmcid, error=str(e))
                xml = None
            if xml is None:
                report.skipped.append(pmcid)
                return
            try:
                meta, passages = parse_jats(xml, pmcid, max_chars=cfg.library.max_passage_chars)
            except ValueError as e:
                log.warning("library_parse_failed", pmcid=pmcid, error=str(e))
                report.skipped.append(pmcid)
                return
            passages = dedupe_anchors(passages)
            if not passages:
                report.skipped.append(pmcid)
                return
            embeddings = None
            if embedder is not None:
                vecs = await embedder.embed([p.text for p in passages])
                embeddings = [[float(x) for x in v] for v in vecs]
            # Await first: `x += await ...` reads x before the await and loses
            # concurrent updates.
            stored = await store.upsert_passages(meta, passages, embeddings=embeddings)
            report.passages += stored
            report.papers += 1

    try:
        pmcids = await search_oa_pmcids(client, query, max_papers)
        await asyncio.gather(*(one(p) for p in pmcids))
    finally:
        if own_http:
            await client.aclose()
    order = {p: i for i, p in enumerate(pmcids)}
    report.skipped.sort(key=order.get)
    report.already_present.sort(key=order.get)
    return report
