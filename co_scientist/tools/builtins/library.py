"""`search_library`: hybrid search over the anchored evidence library (Atlas only)."""

from __future__ import annotations

import time
from typing import Any

from pymongo.errors import OperationFailure

from ...storage import AtlasConn
from ..base import ToolCtx, ToolResult

_TEXT_CHARS = 800


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
        k = max(1, min(20, int(args.get("k") or 8)))
        kind = args.get("kind") or None
        try:
            if await lib_store.count(ctx.db) == 0:
                return ToolResult(
                    is_error=True,
                    error_message="the evidence library is empty (run `library ingest` first)",
                )
            hits = await hybrid_search(ctx.db, ctx.cfg, query, k=k, kind=kind)
        except OperationFailure as e:
            if "index" in str(e).lower():
                return ToolResult(
                    is_error=True,
                    error_message="library search index is not ready yet; retry shortly",
                )
            raise
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
