from __future__ import annotations

from co_scientist.library.jats import PaperMeta, Passage
from co_scientist.storage.atlas import library as lib


def _passages(pmcid: str) -> list[Passage]:
    return [
        Passage(f"{pmcid}#abstract.p1", pmcid, "abstract", "Abstract", None, "First.", 0),
        Passage(f"{pmcid}#F1", pmcid, "figure", "Results", "Figure 1", "Figure 1 cap.", 1),
    ]


async def test_upsert_passages_replaces_on_reingest(atlas_conn):
    meta = PaperMeta("PMC42", "A title", "10.1/x", 2024, "J")
    assert not await lib.has_paper(atlas_conn, "PMC42")
    assert await lib.upsert_passages(atlas_conn, meta, _passages("PMC42")) == 2
    assert await lib.upsert_passages(atlas_conn, meta, _passages("PMC42")) == 2
    assert await lib.count(atlas_conn) == 2
    assert await lib.has_paper(atlas_conn, "PMC42")
    doc = await atlas_conn.coll("library").find_one({"_id": "PMC42#F1"})
    assert doc["url"] == "https://europepmc.org/article/PMC/PMC42#F1"
    assert doc["kind"] == "figure" and doc["year"] == 2024
    assert "embedding" not in doc


async def test_upsert_passages_stores_client_embeddings(atlas_conn):
    meta = PaperMeta("PMC43", "T", None, None, None)
    await lib.upsert_passages(
        atlas_conn, meta, _passages("PMC43"), embeddings=[[0.1, 0.2], [0.3, 0.4]]
    )
    doc = await atlas_conn.coll("library").find_one({"_id": "PMC43#F1"})
    assert doc["embedding"] == [0.3, 0.4]


async def test_journals_by_pmcid_returns_known_journals_only(atlas_conn):
    await lib.upsert_passages(atlas_conn, PaperMeta("PMC50", "T", None, None, "Cell"),
                              _passages("PMC50"))
    await lib.upsert_passages(atlas_conn, PaperMeta("PMC51", "T", None, None, None),
                              _passages("PMC51"))
    got = await lib.journals_by_pmcid(atlas_conn, ["PMC50", "PMC51", "PMC52"])
    assert got == {"PMC50": "Cell"}
    assert await lib.journals_by_pmcid(atlas_conn, []) == {}
