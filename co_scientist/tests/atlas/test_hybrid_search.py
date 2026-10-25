from __future__ import annotations

import asyncio
from functools import partial

from pymongo.errors import OperationFailure

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
    hits = []
    for _ in range(30):
        hits = await hybrid_search(atlas_conn, atlas_cfg, "quixotrel", k=3, kind="figure")
        if hits:
            break
        await asyncio.sleep(10)
    assert hits and hits[0].anchor_id == "PMC900#F2"
    assert hits[0].fused_score > 0


async def test_building_index_error_shape_is_classified(atlas_conn, atlas_cfg):
    """Pins the live error shape that `_building_index` relies on."""
    from co_scientist.storage.atlas.indexes import ensure_indexes
    from co_scientist.tools.builtins.library import _building_index

    await atlas_conn.ensure_collection("library")
    meta = PaperMeta("PMC901", "T", None, 2024, "J")
    await lib.upsert_passages(
        atlas_conn, meta, [Passage("PMC901#p1", "PMC901", "paragraph", "S", None, "x y", 0)]
    )
    # No index yet: the server returns no hits rather than an error.
    assert await hybrid_search(atlas_conn, atlas_cfg, "x", k=2) == []
    await ensure_indexes(atlas_conn, atlas_cfg)
    names = (atlas_cfg.library.search_index, atlas_cfg.library.vector_index)
    try:
        await hybrid_search(atlas_conn, atlas_cfg, "x", k=2)
    except OperationFailure as e:
        assert _building_index(e, names) in names


async def _ready(conn, cfg) -> None:
    lib = cfg.library
    coll = conn.coll("library")
    for name in (lib.search_index, lib.vector_index, lib.scoped_search_index,
                 lib.scoped_vector_index):
        assert await wait_for_search_index(coll, name, timeout_s=900, poll_s=10), name


async def _poll(fn, want, tries=30):
    got = None
    for _ in range(tries):
        got = await fn()
        if want(got):
            return got
        await asyncio.sleep(10)
    return got


async def _store_upload(conn, cfg, sid, filename, text):
    import io
    from datetime import UTC, datetime

    from docx import Document

    from co_scientist import ids
    from co_scientist.library.uploads import ingest_attachment
    from co_scientist.models.attachment import AttachmentMeta
    from co_scientist.storage.repos import attachments, blobs

    d = Document()
    d.add_paragraph(text)
    buf = io.BytesIO()
    d.save(buf)
    blob_id = await blobs.put(conn, "attachments", filename, buf.getvalue(), {})
    meta = AttachmentMeta(
        id=ids.attachment_id(), session_id=sid, filename=filename, content_type="", size=1,
        sha256=filename, kind="document", status="stored", blob_id=blob_id,
        uploaded_at=datetime.now(UTC),
    )
    assert await attachments.insert(conn, meta)
    assert await ingest_attachment(conn, cfg, meta) == 1
    assert (await attachments.fetch(conn, meta.id)).status == "ingested"
    return meta


async def test_upload_passages_visible_only_to_their_session(atlas_conn, atlas_cfg):
    from co_scientist.library import search

    # Legacy Europe PMC passage: no `source` field at all (ruling S1: no backfill needed).
    legacy = {"_id": "PMC777#p1", "pmcid": "PMC777", "title": "Legacy", "kind": "paragraph",
              "section": "S", "text": "Zorblatt legacy europepmc passage about kinases.",
              "url": "https://europepmc.org/article/PMC/PMC777#p1"}
    await atlas_conn.coll("library").insert_one(legacy)
    a = await _store_upload(atlas_conn, atlas_cfg, "SESS_A", "a.docx",
                            "Zorblatt notes uploaded by session A about kinases.")
    b = await _store_upload(atlas_conn, atlas_cfg, "SESS_B", "b.docx",
                            "Zorblatt notes uploaded by session B about kinases.")
    await _ready(atlas_conn, atlas_cfg)
    a_id, b_id = f"UPLOAD{a.id[-12:]}#p1", f"UPLOAD{b.id[-12:]}#p1"

    async def anchors(sid):
        hits = await search.hybrid_search(atlas_conn, atlas_cfg, "zorblatt kinases", k=8,
                                          session_id=sid)
        return {h.anchor_id for h in hits}

    async def scoped_from(sid, branch):
        p = search.build_hybrid_pipeline(atlas_cfg, "zorblatt kinases", k=8, session_id=sid,
                                         scoped=True)
        stages = p[0]["$rankFusion"]["input"]["pipelines"][branch]
        cur = await atlas_conn.coll("library").aggregate([*stages, {"$project": {"_id": 1}}])
        return {d["_id"] for d in await cur.to_list()}

    want_a = {"PMC777#p1", a_id}
    want_b = {"PMC777#p1", b_id}

    async def eventually(fn, want):
        got = await _poll(fn, lambda g: g == want)
        assert got == want, got

    # S1: docs lacking `source` still match in BOTH branches of the scoped (v2) pipeline.
    for branch in ("text", "vector"):
        await eventually(partial(scoped_from, "SESS_A", branch), want_a)
        await eventually(partial(scoped_from, "SESS_B", branch), want_b)
        await eventually(partial(scoped_from, None, branch), {"PMC777#p1"})

    # End to end through hybrid_search on the v2 indexes.
    search._SCOPED_READY.clear()
    await eventually(partial(anchors, "SESS_A"), want_a)
    await eventually(partial(anchors, "SESS_B"), want_b)
    await eventually(partial(anchors, None), {"PMC777#p1"})
    assert search._SCOPED_READY[(atlas_conn.db.name, atlas_conn.prefix)] is True

    # S2 fallback: v1 indexes unfiltered, other sessions dropped in Python.
    search._SCOPED_READY[(atlas_conn.db.name, atlas_conn.prefix)] = False
    await eventually(partial(anchors, "SESS_A"), want_a)
    await eventually(partial(anchors, "SESS_B"), want_b)
    await eventually(partial(anchors, None), {"PMC777#p1"})
    hits = await search.hybrid_search(atlas_conn, atlas_cfg, "zorblatt", k=8, session_id="SESS_A")
    assert next(h for h in hits if h.anchor_id == a_id).url == f"upload://{a.id}#p1"
