"""Web search tool.

Provider priority: Tavily (primary, dev-friendly) → Brave (fallback).
If neither key is present, the tool reports an error to the agent so it can
proceed without web evidence (rather than crash the run).
"""

from __future__ import annotations

import os
import time
from typing import Any

import httpx

from ..config import Config
from .base import ToolCtx, ToolResult

_TAVILY_URL = "https://api.tavily.com/search"
_BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"


class WebSearchTool:
    name = "web_search"
    description = (
        "Search the public web for scientific literature, news, and reference material. "
        "Returns a list of {title, url, snippet, published_at?} results. "
        "Use when you need broad recall across the open web; for indexed databases prefer "
        "pubmed_search, arxiv_search, or europe_pmc_search."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Free-text search query."},
            "max_results": {
                "type": "integer",
                "minimum": 1,
                "maximum": 20,
                "description": "Number of results to return (default 8).",
            },
        },
        "required": ["query"],
    }

    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg

    def _add_line_numbers(self, text: str) -> str:
        """Helper function: Prepends line numbers to each line of text."""
        if not text:
            return ""
        return "\n".join(f"[L{i+1}] {line}" for i, line in enumerate(text.splitlines()))

    async def call(self, args: dict[str, Any], ctx: ToolCtx) -> ToolResult:
        t0 = time.monotonic()
        query = args.get("query", "").strip()
        n = int(args.get("max_results") or self._cfg.web_search.max_results)
        if not query:
            return ToolResult(is_error=True, error_message="empty query")

        tavily = self._cfg.secrets.TAVILY_API_KEY or os.environ.get("TAVILY_API_KEY")
        brave = self._cfg.secrets.BRAVE_API_KEY or os.environ.get("BRAVE_API_KEY")
        provider = self._cfg.web_search.provider.lower()

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                if provider == "tavily" and tavily:
                    results = await self._tavily(client, tavily, query, n)
                elif provider == "brave" and brave:
                    results = await self._brave(client, brave, query, n)
                elif tavily:
                    results = await self._tavily(client, tavily, query, n)
                elif brave:
                    results = await self._brave(client, brave, query, n)
                else:
                    return ToolResult(
                        is_error=True,
                        error_message="no web search API key configured (TAVILY_API_KEY or BRAVE_API_KEY)",
                    )
        except httpx.HTTPError as e:
            return ToolResult(is_error=True, error_message=f"web search failed: {e}")

        payload: dict[str, Any] = {"query": query, "n": len(results), "results": results}
        return ToolResult(
            content=payload,
            duration_ms=int((time.monotonic() - t0) * 1000),
            result_bytes=len(str(payload)),
        )

    async def _tavily(
        self, client: httpx.AsyncClient, key: str, query: str, n: int
    ) -> list[dict[str, Any]]:
        r = await client.post(
            _TAVILY_URL,
            json={
                "api_key": key,
                "query": query,
                "max_results": n,
                "search_depth": "advanced",
                "include_answer": False,
            },
        )
        r.raise_for_status()
        data = r.json()
        out = []
        for hit in data.get("results", [])[:n]:
            out.append(
                {
                    "title": hit.get("title", ""),
                    "url": hit.get("url", ""),
                    "snippet": self._add_line_numbers(hit.get("content", "")),
                    "published_at": hit.get("published_date"),
                    "score": hit.get("score"),
                }
            )
        return out

    async def _brave(
        self, client: httpx.AsyncClient, key: str, query: str, n: int
    ) -> list[dict[str, Any]]:
        r = await client.get(
            _BRAVE_URL,
            headers={"X-Subscription-Token": key, "Accept": "application/json"},
            params={"q": query, "count": n},
        )
        r.raise_for_status()
        data = r.json()
        out = []
        for hit in data.get("web", {}).get("results", [])[:n]:
            out.append(
                {
                    "title": hit.get("title", ""),
                    "url": hit.get("url", ""),
                    "snippet": self._add_line_numbers(hit.get("description", "")),
                    "published_at": hit.get("age"),
                }
            )
        return out


