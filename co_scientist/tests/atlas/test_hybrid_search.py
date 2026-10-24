from __future__ import annotations

from co_scientist.library.jats import PaperMeta, Passage
from co_scientist.library.search import hybrid_search
from co_scientist.storage.atlas import library as lib
from co_scientist.storage.atlas.indexes import wait_for_search_index


async def test_hybrid_search_finds_figure_by_caption(atlas_conn, atlas_cfg):
    meta = PaperMeta("PMC900", "Zorblatt kinase paper", None, 2024, "J")
    passages = [
        Passage("PMC900#F2", "PMC900", "figure", "Results", "Figure 2",
                "Figure 2. Quixotrel phosphorylation of the zorblatt receptor.", 1),
        Passage("PMC900#p1", "PMC900", "paragraph", "Intro", None,
                "Neurons communicate across synapses using neurotransmitters.", 2),
        Passage("PMC900#p2", "PMC900", "paragraph", "Methods", None,
                "Mice were housed under a twelve hour light dark cycle.", 3),
    ]
    await lib.upsert_passages(atlas_conn, meta, passages)
    coll = atlas_conn.coll("library")
    for name in (atlas_cfg.library.search_index, atlas_cfg.library.vector_index):
        assert await wait_for_search_index(coll, name, timeout_s=900, poll_s=10), name
    # Indexes can be queryable before the documents are searchable; retry briefly.
    import asyncio

    hits = []
    for _ in range(30):
        hits = await hybrid_search(atlas_conn, atlas_cfg, "quixotrel", k=3, kind="figure")
        if hits:
            break
        await asyncio.sleep(10)
    assert hits and hits[0].anchor_id == "PMC900#F2"
    assert hits[0].fused_score > 0
