"""Offline tests for library ingest: Europe PMC fetch, dedupe and store hand-off."""

from __future__ import annotations

import asyncio

import httpx
import numpy as np

from co_scientist.config import Config, LibraryCfg
from co_scientist.library.ingest import IngestReport, ingest_query
from co_scientist.storage.atlas.indexes import SEARCH_INDEX_SPECS


def _xml(*paras: str, ids: tuple[str, ...] = ()) -> str:
    body = "".join(
        f'<p id="{i}">{t}</p>' if i else f"<p>{t}</p>"
        for t, i in zip(paras, ids or ("",) * len(paras), strict=True)
    )
    return (
        "<article><front><article-meta><title-group><article-title>T</article-title>"
        "</title-group></article-meta></front>"
        f"<body><sec><title>Results</title>{body}</sec></body></article>"
    )


class FakeStore:
    def __init__(self, present: set[str] | None = None) -> None:
        self.present = present or set()
        self.calls: list[tuple[str, list[str], list[list[float]] | None]] = []

    async def has_paper(self, pmcid: str) -> bool:
        return pmcid in self.present

    async def upsert_passages(self, meta, passages, *, embeddings=None) -> int:
        self.calls.append((meta.pmcid, [p.anchor_id for p in passages], embeddings))
        return len(passages)


def _client(xmls: dict[str, str | int], fetched: list[str] | None = None) -> httpx.AsyncClient:
    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path.endswith("/search"):
            res = [{"pmcid": p} for p in xmls]
            return httpx.Response(200, json={"resultList": {"result": res}})
        pmcid = path.split("/")[-2]
        if fetched is not None:
            fetched.append(pmcid)
        val = xmls[pmcid]
        if isinstance(val, int):
            return httpx.Response(val)
        return httpx.Response(200, text=val)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_ingest_skips_missing_fulltext():
    store = FakeStore()
    async with _client({"PMC1": _xml("alpha"), "PMC2": 404}) as http:
        rep = await ingest_query(None, Config(), "q", http=http, store=store)
    assert isinstance(rep, IngestReport)
    assert rep.skipped == ["PMC2"]
    assert rep.papers == 1
    assert rep.passages == 1


async def test_ingest_is_idempotent_per_paper():
    store = FakeStore(present={"PMC1"})
    fetched: list[str] = []
    async with _client({"PMC1": _xml("alpha")}, fetched) as http:
        rep = await ingest_query(None, Config(), "q", http=http, store=store)
    assert rep.already_present == ["PMC1"]
    assert rep.papers == 0
    assert fetched == []
    assert store.calls == []


async def test_ingest_dedupes_duplicate_anchors():
    store = FakeStore()
    xml = _xml("a", "b", "c", ids=("F2", "F2", "F2"))
    async with _client({"PMC9": xml}) as http:
        await ingest_query(None, Config(), "q", http=http, store=store)
    assert store.calls[0][1] == ["PMC9#F2", "PMC9#F2~2", "PMC9#F2~3"]


async def test_ingest_skips_unparseable_xml():
    store = FakeStore()
    async with _client({"PMC1": "<article><oops>", "PMC2": _xml("ok")}) as http:
        rep = await ingest_query(None, Config(), "q", http=http, store=store)
    assert rep.skipped == ["PMC1"]
    assert rep.papers == 1


class FakeEmbedder:
    model = "fake"
    dim = 3

    async def embed(self, texts: list[str]) -> np.ndarray:
        return np.array([[float(len(t)), 0.0, 1.0] for t in texts])


async def test_ingest_client_mode_embeds_passages(monkeypatch):
    from co_scientist.library import ingest as mod

    monkeypatch.setattr(mod, "make_embedder", lambda cfg: FakeEmbedder())
    store = FakeStore()
    cfg = Config(library=LibraryCfg(embedding="client"))
    async with _client({"PMC1": _xml("aa", "bbbb")}) as http:
        await ingest_query(None, cfg, "q", http=http, store=store)
    embs = store.calls[0][2]
    assert embs == [[2.0, 0.0, 1.0], [4.0, 0.0, 1.0]]


async def test_auto_mode_passes_no_embeddings():
    store = FakeStore()
    async with _client({"PMC1": _xml("aa")}) as http:
        await ingest_query(None, Config(), "q", http=http, store=store)
    assert store.calls[0][2] is None


def test_library_search_specs_registered_with_default_names():
    lib = {s.name: s for s in SEARCH_INDEX_SPECS if s.collection == "library"}
    cfg = LibraryCfg()
    assert set(lib) == {cfg.search_index, cfg.vector_index}
    assert lib[cfg.search_index].type == "search"
    assert lib[cfg.vector_index].type == "vectorSearch"


async def test_ingest_counts_passages_across_concurrent_papers():
    class SlowStore(FakeStore):
        async def upsert_passages(self, meta, passages, *, embeddings=None) -> int:
            await asyncio.sleep(0.01)
            return await super().upsert_passages(meta, passages, embeddings=embeddings)

    xmls = {f"PMC{i}": _xml("a", "b", "c") for i in range(1, 6)}
    async with _client(xmls) as http:
        rep = await ingest_query(None, Config(), "q", http=http, store=SlowStore())
    assert (rep.papers, rep.passages) == (5, 15)


async def test_ingest_records_store_failure_and_continues():
    class BoomStore(FakeStore):
        async def upsert_passages(self, meta, passages, *, embeddings=None) -> int:
            if meta.pmcid == "PMC2":
                raise RuntimeError("bulk write exploded")
            return await super().upsert_passages(meta, passages, embeddings=embeddings)

    store = BoomStore()
    xmls = {f"PMC{i}": _xml("a", "b") for i in (1, 2, 3)}
    async with _client(xmls) as http:
        rep = await ingest_query(None, Config(), "q", http=http, store=store)
    assert (rep.papers, rep.passages) == (2, 4)
    assert len(rep.failed) == 1
    assert rep.failed[0].startswith("PMC2: RuntimeError:")
    assert rep.skipped == []


async def test_ingest_records_transient_fetch_failure():
    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path.endswith("/search"):
            res = [{"pmcid": p} for p in ("PMC1", "PMC2", "PMC3")]
            return httpx.Response(200, json={"resultList": {"result": res}})
        pmcid = path.split("/")[-2]
        if pmcid == "PMC1":
            return httpx.Response(500)
        if pmcid == "PMC2":
            raise httpx.ConnectTimeout("slow", request=req)
        return httpx.Response(200, text=_xml("ok"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        rep = await ingest_query(None, Config(), "q", http=http, store=FakeStore())
    assert rep.skipped == []
    assert [f.split(":")[0] for f in rep.failed] == ["PMC1", "PMC2"]
    assert "HTTPStatusError" in rep.failed[0] and "ConnectTimeout" in rep.failed[1]
    assert rep.papers == 1


def test_passage_url_strips_dedupe_suffix_and_keeps_split_suffix():
    from co_scientist.storage.atlas.library import passage_url

    base = "https://europepmc.org/article/PMC/PMC1"
    assert passage_url("PMC1", "PMC1#F2~2") == f"{base}#F2"
    assert passage_url("PMC1", "PMC1#s1.p2.1~3") == f"{base}#s1.p2.1"
