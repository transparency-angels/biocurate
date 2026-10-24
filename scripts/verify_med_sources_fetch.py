#!/usr/bin/env python3
"""Standalone verification script for medical literature search & web_fetch.

Demonstrates:
1. Keyless, agent-free fetching from biomedical sources (PubMed E-utilities,
   Europe PMC REST API, and full-page `web_fetch` on PubMed / Europe PMC URLs).
2. Default cookie refusal (`cookie_policy = "refuse_all"`, `DNT: 1`, `Sec-GPC: 1`).
3. Every returned text/abstract block has `[L1]`, `[L2]`, ... line numbers
   prepended in front of each line.
"""

from __future__ import annotations

import asyncio
import email.message
import html.parser
import json
import os
import sys
import tempfile
import types
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _install_stdlib_shims_if_needed() -> None:
    """Allow running under bare system python3 if .venv packages aren't active."""
    try:
        import aiosqlite  # noqa: F401
        import httpx  # noqa: F401
        import pydantic  # noqa: F401
        import trafilatura  # noqa: F401
        import ulid  # noqa: F401
        return
    except ImportError:
        pass

    sys.modules.setdefault("ulid", types.SimpleNamespace(ULID=object))
    sys.modules.setdefault("aiosqlite", types.SimpleNamespace(Connection=object))

    class _BaseModel:
        def __init__(self, **kwargs: Any) -> None:
            for k, v in kwargs.items():
                setattr(self, k, v)

    def _field(*, default: Any = None, default_factory: Any = None, **_kw: Any) -> Any:
        return default_factory() if default_factory is not None else default

    sys.modules.setdefault(
        "pydantic", types.SimpleNamespace(BaseModel=_BaseModel, Field=_field)
    )
    sys.modules.setdefault(
        "pydantic_settings",
        types.SimpleNamespace(
            BaseSettings=_BaseModel, SettingsConfigDict=lambda **_kw: {}
        ),
    )

    # Minimal HTML text + title extractor fallback when trafilatura is absent
    class _ArticleHTMLParser(html.parser.HTMLParser):
        _SKIP = frozenset({"script", "style", "noscript", "svg", "nav", "footer", "header"})

        def __init__(self) -> None:
            super().__init__()
            self._skip_depth = 0
            self._in_title = False
            self.title_parts: list[str] = []
            self.lines: list[str] = []
            self._buf: list[str] = []

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            t = tag.lower()
            if t in self._SKIP:
                self._skip_depth += 1
            elif t == "title":
                self._in_title = True
            elif t in {"p", "div", "section", "article", "h1", "h2", "h3", "h4", "li", "br", "tr"}:
                self._flush()

        def handle_endtag(self, tag: str) -> None:
            t = tag.lower()
            if t in self._SKIP and self._skip_depth > 0:
                self._skip_depth -= 1
            elif t == "title":
                self._in_title = False
            elif t in {"p", "div", "section", "article", "h1", "h2", "h3", "h4", "li", "tr"}:
                self._flush()

        def handle_data(self, data: str) -> None:
            if self._in_title:
                self.title_parts.append(data)
            if self._skip_depth == 0:
                self._buf.append(data)

        def _flush(self) -> None:
            if not self._buf:
                return
            line = " ".join("".join(self._buf).split()).strip()
            self._buf.clear()
            if len(line) >= 25:
                self.lines.append(line)

    def _trafilatura_extract(html_str: str, **_kwargs: Any) -> str:
        parser = _ArticleHTMLParser()
        parser.feed(html_str)
        parser._flush()
        return "\n".join(parser.lines)

    def _trafilatura_metadata(html_str: str) -> Any:
        parser = _ArticleHTMLParser()
        parser.feed(html_str)
        title = " ".join("".join(parser.title_parts).split()).strip() or None
        return types.SimpleNamespace(title=title)

    trafilatura_mod = types.ModuleType("trafilatura")
    trafilatura_mod.extract = _trafilatura_extract  # type: ignore[attr-defined]
    trafilatura_mod.metadata = types.SimpleNamespace(  # type: ignore[attr-defined]
        extract_metadata=_trafilatura_metadata
    )
    sys.modules.setdefault("trafilatura", trafilatura_mod)

    # Minimal httpx shim backed by stdlib urllib.request + CookieJar
    httpx_mod = types.ModuleType("httpx")

    class HTTPError(Exception):
        pass

    class RequestError(HTTPError):
        def __init__(self, message: str, request: Any = None) -> None:
            super().__init__(message)
            self.request = request

    class URL:
        def __init__(self, url: str) -> None:
            self._url = str(url)
            self.host = urllib.parse.urlsplit(self._url).hostname or ""

        def join(self, rel: str) -> URL:
            return URL(urllib.parse.urljoin(self._url, rel))

        def __str__(self) -> str:
            return self._url

    class Headers(dict):
        def get(self, key: str, default: Any = None) -> Any:
            low = key.lower()
            for k, v in self.items():
                if k.lower() == low:
                    return v
            return default

        def __contains__(self, key: object) -> bool:
            if not isinstance(key, str):
                return False
            low = key.lower()
            return any(k.lower() == low for k in self.keys())

    class Cookies:
        def __init__(self, jar: Any = None) -> None:
            self.jar = jar

        def extract_cookies(self, response: Any) -> None:
            if self.jar is not None and hasattr(response, "_urllib_resp") and hasattr(response, "_urllib_req"):
                self.jar.extract_cookies(response._urllib_resp, response._urllib_req)

    class _Response:
        def __init__(
            self,
            status_code: int,
            url: str,
            headers: Headers,
            body: bytes,
            urllib_resp: Any = None,
            urllib_req: Any = None,
        ) -> None:
            self.status_code = status_code
            self.url = URL(url)
            self.headers = headers
            self._body = body
            self.text = body.decode("utf-8", errors="replace")
            self.history: list[_Response] = []
            self.request = urllib_req
            self._urllib_resp = urllib_resp
            self._urllib_req = urllib_req

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise HTTPError(f"HTTP {self.status_code}")

        def json(self) -> Any:
            return json.loads(self.text)

        async def __aenter__(self) -> _Response:
            return self

        async def __aexit__(self, *args: Any) -> bool:
            return False

        async def aiter_bytes(self):
            yield self._body

    class AsyncClient:
        def __init__(
            self,
            *,
            timeout: float = 30.0,
            headers: dict[str, str] | None = None,
            cookies: Cookies | None = None,
            **_kwargs: Any,
        ) -> None:
            self._timeout = timeout
            self._headers = dict(headers or {"User-Agent": "co-scientist/0.1"})
            self._cookies = cookies

        async def __aenter__(self) -> AsyncClient:
            return self

        async def __aexit__(self, *args: Any) -> bool:
            return False

        def _do_sync(self, method: str, url: str, params: dict[str, Any] | None = None) -> _Response:
            if params:
                qs = urllib.parse.urlencode(params)
                sep = "&" if "?" in url else "?"
                url = f"{url}{sep}{qs}"
            req = urllib.request.Request(url, headers=self._headers, method=method)
            if self._cookies is not None and self._cookies.jar is not None:
                self._cookies.jar.add_cookie_header(req)
            try:
                with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                    body = resp.read()
                    hdrs = Headers({k: v for k, v in resp.headers.items()})
                    if self._cookies is not None and self._cookies.jar is not None:
                        self._cookies.jar.extract_cookies(resp, req)
                    return _Response(resp.status, resp.geturl(), hdrs, body, resp, req)
            except urllib.error.HTTPError as e:
                body = e.read() if hasattr(e, "read") else b""
                hdrs = Headers({k: v for k, v in (e.headers.items() if e.headers else [])})
                return _Response(e.code, url, hdrs, body, e, req)
            except Exception as e:
                raise HTTPError(str(e)) from e

        async def get(self, url: str, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> _Response:
            if headers:
                self._headers.update(headers)
            return await asyncio.to_thread(self._do_sync, "GET", url, params)

        def stream(self, method: str, url: str) -> _Response:
            return self._do_sync(method, url)

    httpx_mod.HTTPError = HTTPError  # type: ignore[attr-defined]
    httpx_mod.RequestError = RequestError  # type: ignore[attr-defined]
    httpx_mod.URL = URL  # type: ignore[attr-defined]
    httpx_mod.Headers = Headers  # type: ignore[attr-defined]
    httpx_mod.Cookies = Cookies  # type: ignore[attr-defined]
    httpx_mod.AsyncClient = AsyncClient  # type: ignore[attr-defined]
    httpx_mod.Response = _Response  # type: ignore[attr-defined]
    sys.modules.setdefault("httpx", httpx_mod)


_install_stdlib_shims_if_needed()

from co_scientist.config import Config  # noqa: E402
from co_scientist.tools.base import ToolCtx  # noqa: E402
from co_scientist.tools.builtins.europe_pmc import EuropePMCSearchTool  # noqa: E402
from co_scientist.tools.builtins.pubmed import PubmedSearchTool  # noqa: E402
from co_scientist.tools.web_fetch import WebFetchTool, _make_cookie_jar  # noqa: E402


async def main() -> None:
    # Ensure no LLM or search API keys are used
    for key in (
        "GEMINI_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "OPENROUTER_API_KEY",
        "TAVILY_API_KEY",
        "BRAVE_API_KEY",
        "NCBI_API_KEY",
    ):
        os.environ.pop(key, None)

    with tempfile.TemporaryDirectory(prefix="med_fetch_demo_") as tmp_dir:
        cfg = Config()
        cfg.storage.data_dir = tmp_dir
        ctx = ToolCtx(cfg=cfg, db=None, session_id="ses_demo")

        print("=" * 78)
        print("1. COOKIE POLICY CHECK (Default: refuse_all)")
        print("=" * 78)
        print(f"Configured web_fetch.cookie_policy: {cfg.web_fetch.cookie_policy!r}")
        jar = _make_cookie_jar(cfg.web_fetch.cookie_policy, "pubmed.ncbi.nlm.nih.gov")
        req = urllib.request.Request("https://pubmed.ncbi.nlm.nih.gov/")
        msg = email.message.Message()
        msg.add_header("Set-Cookie", "_ga=GA1.1.999; Domain=.nih.gov; Path=/")
        msg.add_header("Set-Cookie", "ncbi_sid=12345; Domain=.nih.gov; Path=/")
        jar.extract_cookies(types.SimpleNamespace(info=lambda: msg), req)  # type: ignore[arg-type]
        print(f"Cookies stored after Set-Cookie headers under 'refuse_all': {len(jar)} (expected 0)\n")

        query = "microbiome inflammation short-chain fatty acids"

        print("=" * 78)
        print(f"2. PUBMED SEARCH (keyless, agent-free) — query={query!r}")
        print("=" * 78)
        pubmed = PubmedSearchTool(cfg)
        pm_res = await pubmed.call({"query": query, "max_results": 2}, ctx)
        assert not pm_res.is_error, f"PubMed error: {pm_res.error_message}"
        pm_hits = pm_res.content["results"]
        print(f"Returned {len(pm_hits)} PubMed records.")
        first_pubmed_url = None
        for idx, hit in enumerate(pm_hits, 1):
            print(f"\n--- PubMed Hit #{idx}: PMID {hit['pmid']} ({hit['year']}) ---")
            print(f"Title: {hit['title']}")
            print(f"URL:   {hit['url']}")
            print("Abstract (with [L#] line numbers prepended):")
            for line in (hit["abstract"] or "").splitlines()[:5]:
                print(f"  {line}")
            if first_pubmed_url is None and hit.get("url"):
                first_pubmed_url = hit["url"]

        print("\n" + "=" * 78)
        print(f"3. EUROPE PMC SEARCH (keyless, agent-free) — query={query!r}")
        print("=" * 78)
        epmc = EuropePMCSearchTool()
        epmc_res = await epmc.call(
            {"query": query, "max_results": 2, "open_access_only": True}, ctx
        )
        assert not epmc_res.is_error, f"Europe PMC error: {epmc_res.error_message}"
        epmc_hits = epmc_res.content["results"]
        print(f"Returned {len(epmc_hits)} Europe PMC open-access records.")
        first_epmc_url = None
        for idx, hit in enumerate(epmc_hits, 1):
            print(f"\n--- Europe PMC Hit #{idx}: {hit['id']} ({hit['year']}) ---")
            print(f"Title: {hit['title']}")
            print(f"URL:   {hit['url']}")
            print("Abstract (with [L#] line numbers prepended):")
            for line in (hit["abstract"] or "").splitlines()[:5]:
                print(f"  {line}")
            if first_epmc_url is None and hit.get("url"):
                first_epmc_url = hit["url"]

        fetcher = WebFetchTool(cfg)
        for label, target_url in [
            (
                "4A. WEB_FETCH FROM PUBMED ARTICLE URL (cookies refused, [L#] prepended)",
                first_pubmed_url or "https://pubmed.ncbi.nlm.nih.gov/38565643/",
            ),
            (
                "4B. WEB_FETCH FROM EUROPE PMC OPEN-ACCESS URL (cookies refused, [L#] prepended)",
                first_epmc_url or "https://europepmc.org/article/PMC/PMC13666990",
            ),
        ]:
            print("\n" + "=" * 78)
            print(label)
            print("=" * 78)
            fetch_res = await fetcher.call({"url": target_url, "max_chars": 4000}, ctx)
            assert not fetch_res.is_error, f"web_fetch error: {fetch_res.error_message}"
            content = fetch_res.content
            print(f"Fetched URL:  {content['url']}")
            print(f"HTTP Status:  {content['status']}")
            print(f"Content-Type: {content['content_type']}")
            print(f"Bytes:        {content['bytes']}")
            print(f"Title:        {content['title']}")
            lines = (content["text"] or "").splitlines()
            print(f"Total extracted lines: {len(lines)}")
            for i, line in enumerate(lines, 1):
                assert line.startswith(f"[L{i}] "), f"Line {i} missing [L{i}] prefix: {line!r}"
            print("\nFirst 10 lines of extracted content (showing [L#] prefixes):")
            for line in lines[:10]:
                print(f"  {line[:115]}")


if __name__ == "__main__":
    asyncio.run(main())
