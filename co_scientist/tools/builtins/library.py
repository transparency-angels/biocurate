"""`search_library`: hybrid search over the anchored evidence library (Atlas only)."""

from __future__ import annotations

import time
from typing import Any

from pymongo.errors import OperationFailure, PyMongoError

from ...logging import get_logger
from ...storage import AtlasConn
from ..base import ToolCtx, ToolResult

_TEXT_CHARS = 800
log = get_logger(__name__)


def _not_ready(name: str) -> ToolResult:
    return ToolResult(
        is_error=True, error_message=f"library index '{name}' is not ready yet; retry shortly"
    )


def _building_index(e: PyMongoError, names: tuple[str, ...]) -> str | None:
    """Name of the index a query hit while it was still building, else None.

    Observed live (8.0.34): OperationFailure code 8 (UnknownError) with
    "cannot query search index <id> (index <name> collection ...) while in state
    INITIAL_SYNC". No distinct code exists, so match that phrase plus a configured name.
    """
    if not isinstance(e, OperationFailure) or e.code != 8:
        return None
    msg = str(e)
    if "cannot query search index" not in msg:
        return None
    return next((n for n in names if f"index {n} " in msg), None)


async def _unready_index(db: AtlasConn, names: tuple[str, ...]) -> str | None:
    """On an empty result: the first configured index that isn't queryable yet."""
    cur = await db.coll("library").list_search_indexes()
    ready = {d["name"] for d in await cur.to_list() if d.get("queryable")}
    return next((n for n in names if n not in ready), None)


class SearchLibraryTool:
    name = "search_library"
    description = (
        "Search the evidence library of full-text papers (hybrid keyword + semantic, reranked). "
        "Returns passages {anchor_id, pmcid, title, section, kind, label, text, url, score, "
        "rerank_score}. Cite the anchor_id (e.g. PMC1234567#F2) for evidence you use."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "k": {"type": "integer", "minimum": 1, "maximum": 20, "default": 8},
            "kind": {"type": "string", "enum": ["paragraph", "figure", "table", "abstract"]},
        },
        "required": ["query"],
    }

    async def call(self, args: dict[str, Any], ctx: ToolCtx) -> ToolResult:
        from ...library.search import hybrid_search
        from ...storage.atlas import library as lib_store

        t0 = time.monotonic()
        query = str(args.get("query") or "").strip()
        if not query:
            return ToolResult(is_error=True, error_message="empty query")
        if not isinstance(ctx.db, AtlasConn):
            return ToolResult(
                is_error=True, error_message="search_library needs the Atlas storage backend"
            )
        try:
            k = max(1, min(20, int(args.get("k") or 8)))
        except (TypeError, ValueError):
            return ToolResult(is_error=True, error_message="k must be an integer from 1 to 20")
        kind = args.get("kind") or None
        kinds = self.input_schema["properties"]["kind"]["enum"]
        if kind is not None and kind not in kinds:
            return ToolResult(
                is_error=True, error_message=f"kind must be one of {', '.join(kinds)}"
            )
        lib_cfg = ctx.cfg.library
        names = (lib_cfg.search_index, lib_cfg.vector_index)
        building = (*names, lib_cfg.scoped_search_index, lib_cfg.scoped_vector_index)
        try:
            if await lib_store.count(ctx.db) == 0:
                return ToolResult(
                    is_error=True,
                    error_message="the evidence library is empty (run `library ingest` first)",
                )
            hits = await hybrid_search(
                ctx.db, ctx.cfg, query, k=k, kind=kind, session_id=ctx.session_id
            )
            if not hits and (missing := await _unready_index(ctx.db, names)):
                return _not_ready(missing)
        except PyMongoError as e:
            if (name := _building_index(e, building)) is not None:
                return _not_ready(name)
            log.warning("search_library_failed", error=type(e).__name__)
            return ToolResult(
                is_error=True,
                error_message=(
                    f"library search failed ({type(e).__name__}); "
                    "try again or continue without library evidence"
                ),
            )
        payload = {
            "query": query,
            "n": len(hits),
            "hits": [
                {
                    "anchor_id": h.anchor_id,
                    "pmcid": h.pmcid,
                    "title": h.title,
                    "section": h.section,
                    "kind": h.kind,
                    "label": h.label,
                    "text": h.text[:_TEXT_CHARS],
                    "url": h.url,
                    "score": h.fused_score,
                    "rerank_score": h.rerank_score,
                }
                for h in hits
            ],
        }
        return ToolResult(
            content=payload,
            duration_ms=int((time.monotonic() - t0) * 1000),
            result_bytes=len(str(payload)),
        )
