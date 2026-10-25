"""Evidence-library storage on Atlas: anchored passages keyed by `anchor_id`."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pymongo import ReplaceOne

if TYPE_CHECKING:
    from ...library.jats import PaperMeta, Passage
    from .client import AtlasConn

_DEDUPE_SUFFIX = re.compile(r"~\d+$")


def passage_url(pmcid: str, anchor_id: str, *, attachment_id: str | None = None) -> str:
    """Link to the passage; ingest's `~N` dedupe suffix is not a real fragment.

    Uploads (`attachment_id` given) get `upload://{attachment_id}#{fragment}`.
    """
    fragment = _DEDUPE_SUFFIX.sub("", anchor_id.split("#", 1)[-1])
    if attachment_id:
        return f"upload://{attachment_id}#{fragment}"
    return f"https://europepmc.org/article/PMC/{pmcid}#{fragment}"


async def upsert_passages(
    conn: AtlasConn,
    meta: PaperMeta,
    passages: list[Passage],
    *,
    embeddings: list[list[float]] | None = None,
    source: str = "europepmc",
    session_id: str | None = None,
    attachment_id: str | None = None,
) -> int:
    """Replace-upsert each passage by `_id = anchor_id`; returns the passage count.

    `source`/`session_id` scope search: uploads carry `source="upload"` and their session.
    """
    if not passages:
        return 0
    if embeddings is not None and len(embeddings) != len(passages):
        raise ValueError("embeddings must match passages one-to-one")
    now = datetime.now(UTC)
    ops = []
    for i, p in enumerate(passages):
        doc = {
            "_id": p.anchor_id,
            "pmcid": meta.pmcid,
            "title": meta.title,
            "doi": meta.doi,
            "year": meta.year,
            "journal": meta.journal,
            "kind": p.kind,
            "section": p.section,
            "label": p.label,
            "text": p.text,
            "ordinal": p.ordinal,
            "url": passage_url(meta.pmcid, p.anchor_id, attachment_id=attachment_id),
            "source": source,
            "ingested_at": now,
        }
        if session_id is not None:
            doc["session_id"] = session_id
        if embeddings is not None:
            doc["embedding"] = embeddings[i]
        ops.append(ReplaceOne({"_id": p.anchor_id}, doc, upsert=True))
    await conn.coll("library").bulk_write(ops, ordered=False)
    return len(ops)


async def has_paper(conn: AtlasConn, pmcid: str) -> bool:
    return await conn.coll("library").find_one({"pmcid": pmcid}, {"_id": 1}) is not None


async def count(conn: AtlasConn) -> int:
    return await conn.coll("library").count_documents({})
