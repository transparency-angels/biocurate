"""Web fetch: pull a URL, extract clean text, cache on disk by URL hash.

- HTML → trafilatura.extract
- PDF (Content-Type or .pdf suffix) → pypdf text extraction
- Cap: 5 MB by default; 5 redirects max
- Cache: data/artifacts/<session>/papers/<sha1(url)>.json (survives resume)
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import re
import socket
import time
from http.cookiejar import Cookie, CookieJar, DefaultCookiePolicy
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET

import httpx

from ..config import Config, CookiePolicyMode
from ..ids import url_hash
from .base import ToolCtx, ToolResult

# Non-essential cookie names, prefixes, and substrings (analytics, advertising,
# cross-site tracking, marketing automation, telemetry, and consent banners).
# Refused even when the fallback essential-only cookie jar is used.
_NON_ESSENTIAL_COOKIE_EXACT: frozenset[str] = frozenset(
    {
        "_ga",
        "_gid",
        "_gat",
        "_fbp",
        "_fbc",
        "_ttp",
        "_scid",
        "_sctr",
        "sc_at",
        "ide",
        "test_cookie",
        "dsid",
        "flc",
        "aid",
        "taid",
        "exchange_uid",
        "fr",
        "datr",
        "sb",
        "wd",
        "muid",
        "cluid",
        "anonchk",
        "mr",
        "sm",
        "bcookie",
        "bscookie",
        "lidc",
        "ln_or",
        "personalization_id",
        "guest_id",
        "muc_ads",
        "hubspotutk",
        "vuid",
        "mbox",
        "s_cc",
        "s_sq",
        "s_vi",
        "s_ecid",
        "fs_uid",
        "_mkto_trk",
        "optanonconsent",
        "optanonalertboxclosed",
        "cookieconsent",
        "euconsent",
        "euconsent-v2",
        "eupubconsent",
        "eupubconsent-v2",
    }
)

_NON_ESSENTIAL_COOKIE_PREFIXES: tuple[str, ...] = (
    "_ga_",
    "_gat_",
    "_gcl_",
    "_gac_",
    "__gads",
    "__gpi",
    "__utm",
    "_opt_",
    "fpm_",
    "_uet",
    "_clck",
    "_clsk",
    "_tt_",
    "_pin_",
    "_pinterest_",
    "li_",
    "_rdt_",
    "amp_",
    "amplitude",
    "mp_",
    "ajs_",
    "__hs",
    "_hj",
    "intercom-",
    "optimizely",
    "_hp2_",
    "_vis_opt_",
    "_vwo_",
    "amcv_",
    "amcvs_",
    "utag_",
    "pardot",
    "visitor_id",
    "elq",
    "optanon",
    "cmapi_",
    "notice_behavior",
    "notice_gdpr",
    "didomi_",
    "osano_",
)

_NON_ESSENTIAL_COOKIE_SUBSTRINGS: tuple[str, ...] = (
    "track",
    "analytics",
    "advert",
    "adserver",
    "pixel",
    "retarget",
    "affil",
    "utm_",
    "campaign",
    "telemetry",
    "beacon",
    "fingerprint",
    "consent",
)

_META_REFRESH_RE = re.compile(
    r"<meta\b[^>]*?\bhttp-equiv\s*=\s*['\"]?refresh['\"]?[^>]*?>",
    re.IGNORECASE | re.DOTALL,
)
_META_CONTENT_URL_RE = re.compile(
    r"\bcontent\s*=\s*['\"]?\s*\d+(?:\.\d+)?\s*;\s*url\s*=\s*([^'\">\s]+)",
    re.IGNORECASE,
)


def _is_non_essential_cookie_name(name: str) -> bool:
    low = (name or "").strip().lower()
    if not low:
        return True
    if low in _NON_ESSENTIAL_COOKIE_EXACT:
        return True
    if low.startswith(_NON_ESSENTIAL_COOKIE_PREFIXES):
        return True
    return any(sub in low for sub in _NON_ESSENTIAL_COOKIE_SUBSTRINGS)


def _is_same_party_domain(cookie_domain: str, host: str) -> bool:
    host = (host or "").strip(".").lower()
    if not host:
        return False
    cdom = (cookie_domain or "").lstrip(".").lower()
    if cdom.endswith(".local"):
        cdom = cdom[: -len(".local")]
    if not cdom:
        return True
    if "." not in cdom and cdom != host:
        return False
    return host == cdom or host.endswith("." + cdom)


def _request_hostname(request: Any, fallback: str) -> str:
    if request is not None:
        get_full_url = getattr(request, "get_full_url", None)
        if callable(get_full_url):
            try:
                h = urlsplit(get_full_url()).hostname
                if h:
                    return h.lower()
            except Exception:
                pass
        raw_host = getattr(request, "host", None)
        if isinstance(raw_host, str) and raw_host:
            return raw_host.split(":")[0].lower()
    return fallback


class _RefuseAllCookiePolicy(DefaultCookiePolicy):
    """Default privacy policy: refuses every incoming Set-Cookie and never sends
    any Cookie header."""

    def set_ok(self, cookie: Cookie, request: Any) -> bool:
        return False

    def return_ok(self, cookie: Cookie, request: Any) -> bool:
        return False


class _EssentialOnlyCookiePolicy(DefaultCookiePolicy):
    """Refuses all third-party, tracking, analytics, advertising, and consent
    cookies; permits only strictly-necessary same-host session/anti-bot cookies
    for the single in-flight fetch."""

    def __init__(self, origin_host: str) -> None:
        super().__init__()
        self._origin_host = (origin_host or "").strip(".").lower()

    def is_cookie_allowed(self, cookie: Cookie, request: Any = None) -> bool:
        if _is_non_essential_cookie_name(cookie.name):
            return False
        req_host = _request_hostname(request, self._origin_host)
        if not _is_same_party_domain(cookie.domain, self._origin_host):
            return False
        return _is_same_party_domain(cookie.domain, req_host)

    def set_ok(self, cookie: Cookie, request: Any) -> bool:
        if not self.is_cookie_allowed(cookie, request):
            return False
        return super().set_ok(cookie, request)

    def return_ok(self, cookie: Cookie, request: Any) -> bool:
        if not self.is_cookie_allowed(cookie, request):
            return False
        return super().return_ok(cookie, request)


class _PolicyCookieJar(CookieJar):
    """CookieJar that also enforces `_RefuseAllCookiePolicy` /
    `_EssentialOnlyCookiePolicy` on direct `set_cookie` calls."""

    def set_cookie(self, cookie: Cookie) -> None:
        if isinstance(self._policy, _RefuseAllCookiePolicy):
            return
        if isinstance(
            self._policy, _EssentialOnlyCookiePolicy
        ) and not self._policy.is_cookie_allowed(cookie):
            return
        super().set_cookie(cookie)


def _make_cookie_jar(mode: CookiePolicyMode, origin_host: str) -> CookieJar:
    if mode == "refuse_all":
        return _PolicyCookieJar(policy=_RefuseAllCookiePolicy())
    if mode == "essential_only":
        return _PolicyCookieJar(policy=_EssentialOnlyCookiePolicy(origin_host))
    return CookieJar()


def _request_headers(user_agent: str) -> dict[str, str]:
    """Standard content-negotiation headers plus explicit Do-Not-Track /
    Global Privacy Control signals to refuse non-essential tracking."""
    return {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "DNT": "1",
        "Sec-GPC": "1",
    }


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\[\"'])")

_CHALLENGE_STUB_MARKERS: tuple[str, ...] = (
    "enable cookies",
    "reload this page to continue",
    "enable javascript",
    "javascript is required",
    "checking your browser",
    "verify you are human",
    "just a moment...",
)

_PUBMED_URL_RE = re.compile(
    r"^https?://(?:www\.)?(?:pubmed\.ncbi\.nlm\.nih\.gov|ncbi\.nlm\.nih\.gov/pubmed)/(\d+)/?(?:[?#].*)?$",
    re.IGNORECASE,
)
_EPMC_MED_URL_RE = re.compile(
    r"^https?://(?:www\.)?europepmc\.org/article/med/(\d+)/?(?:[?#].*)?$",
    re.IGNORECASE,
)
_PMC_URL_RE = re.compile(
    r"^https?://(?:www\.)?(?:pmc\.ncbi\.nlm\.nih\.gov/articles|ncbi\.nlm\.nih\.gov/pmc/articles|europepmc\.org/articles?|europepmc\.org/article/pmc)/(PMC\d+)/?(?:[?#].*)?$",
    re.IGNORECASE,
)


def _add_line_numbers(text: str) -> str:
    """Prepends line numbers ([L1], [L2], ...) to each line of text.
    Long single-block paragraphs are split on sentence boundaries so each
    sentence gets a distinct line number for citation verification."""
    if not text:
        return ""
    if text.lstrip().startswith("[L1] "):
        return text
    lines: list[str] = []
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        if len(stripped) > 140:
            parts = [p.strip() for p in _SENTENCE_SPLIT_RE.split(stripped) if p.strip()]
            lines.extend(parts)
        else:
            lines.append(stripped)
    return "\n".join(f"[L{i+1}] {line}" for i, line in enumerate(lines))


def _is_challenge_stub(text: str, status: int) -> bool:
    """Detect WAF / cookie / JS challenge stubs (such as AWS WAF HTTP 203
    'Enable cookies for ... and reload this page to continue.')."""
    if status == 203:
        return True
    cleaned = (text or "").strip().lower()
    if not cleaned:
        return False
    return len(cleaned) < 400 and any(m in cleaned for m in _CHALLENGE_STUB_MARKERS)


def _parse_biomed_url(url: str) -> tuple[str | None, str | None]:
    """Return `(pmid, pmcid)` if `url` points to a PubMed, PMC, or Europe PMC
    article page."""
    m = _PUBMED_URL_RE.match(url) or _EPMC_MED_URL_RE.match(url)
    if m:
        return m.group(1), None
    m = _PMC_URL_RE.match(url)
    if m:
        return None, m.group(1).upper()
    return None, None


def _extract_meta_refresh_url(html: str, base_url: str) -> str | None:
    """If `html` contains a `<meta http-equiv="refresh" content="...; url=...">`
    tag, resolve and return the target http(s) URL."""
    for match in _META_REFRESH_RE.finditer(html[:16_384]):
        tag = match.group(0)
        url_match = _META_CONTENT_URL_RE.search(tag)
        if not url_match:
            continue
        raw_target = url_match.group(1).strip().strip("'\"")
        if not raw_target:
            continue
        try:
            resolved = (
                httpx.URL(raw_target)
                if raw_target.startswith(("http://", "https://"))
                else httpx.URL(base_url).join(raw_target)
            )
        except Exception:
            continue
        resolved_str = str(resolved)
        if resolved_str.startswith(("http://", "https://")):
            return resolved_str
    return None


def _is_private_ip(host: str) -> bool:
    """Return True if `host` resolves to any private / loopback / link-local /
    reserved IP. Used to block SSRF against the metadata service and intranet
    targets even when the user-supplied URL passes the scheme check.
    """
    try:
        ip = ipaddress.ip_address(host)
        return (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        )
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        # If we can't resolve, be conservative: refuse.
        return True
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr.split("%")[0])
        except ValueError:
            continue
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return True
    return False


class WebFetchTool:
    name = "web_fetch"
    description = (
        "Fetch a URL and return its main text content (HTML → cleaned text; PDF → extracted text). "
        "Returns {url, title?, text, content_type, status, bytes}. "
        "Use after web_search / arxiv_search / pubmed_search to read the actual content."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Absolute http(s) URL."},
            "max_chars": {
                "type": "integer",
                "minimum": 200,
                "maximum": 200_000,
                "description": "Truncate text to this many characters (default 30000).",
            },
        },
        "required": ["url"],
    }

    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg

    async def call(self, args: dict[str, Any], ctx: ToolCtx) -> ToolResult:
        t0 = time.monotonic()
        url = args.get("url", "").strip()
        max_chars = int(args.get("max_chars") or 30_000)
        if not url.startswith(("http://", "https://")):
            return ToolResult(is_error=True, error_message="URL must start with http(s)")

        # SSRF guard. We re-check after each hop via an httpx event_hook so a
        # redirect can't bounce us to 169.254.169.254 / 127.0.0.1 / RFC1918.
        host = urlsplit(url).hostname or ""
        if not host:
            return ToolResult(is_error=True, error_message="URL has no host")
        if await asyncio.to_thread(_is_private_ip, host):
            return ToolResult(
                is_error=True,
                error_message="URL resolves to a private/loopback address",
            )

        cached = await self._read_cache(ctx, url)
        if cached is not None:
            cached = self._truncate(cached, max_chars)
            return ToolResult(
                content=cached,
                duration_ms=int((time.monotonic() - t0) * 1000),
                result_bytes=len(json.dumps(cached)),
            )

        max_bytes = self._cfg.web_fetch.max_bytes
        policy_mode: CookiePolicyMode = getattr(
            self._cfg.web_fetch, "cookie_policy", "refuse_all"
        )
        req_headers = _request_headers(self._cfg.web_fetch.user_agent)

        # For indexed biomedical article URLs (PubMed, PMC, Europe PMC), prefer
        # the official cookie-free, keyless XML endpoints (NCBI E-utilities /
        # Europe PMC JATS fullTextXML) so we avoid AWS WAF HTTP 203 cookie
        # challenges and Angular SPA shells.
        if _parse_biomed_url(url) != (None, None):
            biomed = await _try_biomed_api_fallback(
                url,
                timeout=self._cfg.web_fetch.timeout_seconds,
                headers=req_headers,
            )
            if biomed is not None:
                text, title, ct, status, total = biomed
                payload = {
                    "url": url,
                    "title": title,
                    "text": _add_line_numbers(text),
                    "content_type": ct,
                    "status": status,
                    "bytes": total,
                }
                await self._write_cache(ctx, url, payload)
                payload = self._truncate(payload, max_chars)
                return ToolResult(
                    content=payload,
                    duration_ms=int((time.monotonic() - t0) * 1000),
                    result_bytes=len(json.dumps(payload)),
                )

        async def _check_redirect(response: httpx.Response) -> None:
            loc = response.headers.get("location")
            if not loc:
                return
            next_url = httpx.URL(loc) if loc.startswith(("http://", "https://")) else response.url.join(loc)
            next_host = next_url.host
            if not next_host or await asyncio.to_thread(_is_private_ip, next_host):
                raise httpx.RequestError(
                    "redirect to private/loopback address blocked",
                    request=response.request,
                )

        async def _fetch_once(
            target_url: str, jar: CookieJar
        ) -> tuple[bytes, str, int, httpx.Headers, list[httpx.Response]] | ToolResult:
            try:
                # Stream so we can abort on size-overflow without buffering the
                # full body in memory.
                async with (
                    httpx.AsyncClient(
                        timeout=self._cfg.web_fetch.timeout_seconds,
                        follow_redirects=True,
                        max_redirects=5,
                        headers=req_headers,
                        cookies=httpx.Cookies(jar),
                        event_hooks={"response": [_check_redirect]},
                    ) as client,
                    client.stream("GET", target_url) as r,
                ):
                    if r.status_code >= 400:
                        return ToolResult(
                            is_error=True,
                            error_message=f"HTTP {r.status_code}",
                            content={"url": target_url, "status": r.status_code},
                        )
                    # Reject upfront if server advertises a too-large body.
                    cl = r.headers.get("content-length")
                    if cl is not None:
                        try:
                            if int(cl) > max_bytes:
                                return ToolResult(
                                    is_error=True,
                                    error_message=f"response too large ({cl} bytes advertised)",
                                )
                        except ValueError:
                            pass

                    chunks: list[bytes] = []
                    total_bytes = 0
                    async for chunk in r.aiter_bytes():
                        total_bytes += len(chunk)
                        if total_bytes > max_bytes:
                            return ToolResult(
                                is_error=True,
                                error_message=f"response too large (>{max_bytes} bytes, stopped streaming)",
                            )
                        chunks.append(chunk)
                    return (
                        b"".join(chunks),
                        str(r.url),
                        r.status_code,
                        r.headers,
                        [*r.history, r],
                    )
            except httpx.HTTPError as e:
                return ToolResult(is_error=True, error_message=f"fetch failed: {e}")

        jar = _make_cookie_jar(policy_mode, host)
        fetched = await _fetch_once(url, jar)
        if isinstance(fetched, ToolResult):
            return fetched
        body, final_url, status, headers, responses = fetched
        total = len(body)

        ct = (headers.get("Content-Type") or "").lower()
        is_pdf = "application/pdf" in ct or final_url.lower().endswith(".pdf") or url.lower().endswith(".pdf")
        try:
            if is_pdf:
                text = await asyncio.to_thread(_extract_pdf, body)
                title: str | None = None
            else:
                html_str = body.decode("utf-8", errors="replace")
                text, title = await asyncio.to_thread(
                    _extract_html, html_str, final_url
                )
                if _is_challenge_stub(text, status):
                    text, title = "", None
                # If Pass 1 refused all cookies (or landed on a meta-refresh
                # gate) and extracted no text, perform at most one ephemeral
                # retry with strictly-necessary same-host cookies (still
                # blocking all third-party, analytics, ad, and consent cookies).
                if not text.strip():
                    refresh_url = _extract_meta_refresh_url(html_str, final_url)
                    has_set_cookie = any(
                        "set-cookie" in resp.headers for resp in responses
                    )
                    retry_jar: CookieJar | None = None
                    retry_url: str | None = None

                    if policy_mode == "refuse_all" and (
                        has_set_cookie or refresh_url is not None
                    ):
                        essential_jar = _make_cookie_jar("essential_only", host)
                        cookie_helper = httpx.Cookies(essential_jar)
                        for resp in responses:
                            cookie_helper.extract_cookies(resp)
                        if len(essential_jar) > 0 or refresh_url is not None:
                            retry_jar = essential_jar
                            retry_url = refresh_url or final_url
                    elif refresh_url is not None:
                        retry_jar = jar
                        retry_url = refresh_url

                    if retry_jar is not None and retry_url is not None:
                        retry_host = urlsplit(retry_url).hostname or ""
                        if retry_host and not await asyncio.to_thread(
                            _is_private_ip, retry_host
                        ):
                            fetched2 = await _fetch_once(retry_url, retry_jar)
                            if not isinstance(fetched2, ToolResult):
                                body2, final_url2, status2, headers2, _ = fetched2
                                ct2 = (headers2.get("Content-Type") or "").lower()
                                is_pdf2 = "application/pdf" in ct2 or final_url2.lower().endswith(".pdf")
                                if is_pdf2:
                                    text2 = await asyncio.to_thread(_extract_pdf, body2)
                                    title2 = None
                                else:
                                    text2, title2 = await asyncio.to_thread(
                                        _extract_html,
                                        body2.decode("utf-8", errors="replace"),
                                        final_url2,
                                    )
                                    if _is_challenge_stub(text2, status2):
                                        text2, title2 = "", None
                                body, final_url, status, headers = (
                                    body2,
                                    final_url2,
                                    status2,
                                    headers2,
                                )
                                ct = ct2
                                total = len(body2)
                                text, title = text2, title2

                # If HTML extraction yielded nothing (e.g. AWS WAF HTTP 203
                # cookie challenge on pubmed.ncbi.nlm.nih.gov or SPA shell on
                # europepmc.org), fall back to cookie-free, keyless official
                # biomedical XML APIs (NCBI E-utilities / Europe PMC REST).
                if not text.strip():
                    biomed = await _try_biomed_api_fallback(
                        final_url or url,
                        timeout=self._cfg.web_fetch.timeout_seconds,
                        headers=req_headers,
                    )
                    if biomed is not None:
                        text, title, ct, status, total = biomed
        except Exception as e:
            return ToolResult(
                is_error=True, error_message=f"extraction failed: {e}"
            )

        payload: dict[str, Any] = {
            "url": final_url,
            "title": title,
            "text": _add_line_numbers(text) if text.strip() else "",
            "content_type": ct,
            "status": status,
            "bytes": total,
        }
        if not text.strip():
            return ToolResult(
                is_error=True,
                error_message="empty text extracted (page may require JavaScript or cookies)",
                content=payload,
                duration_ms=int((time.monotonic() - t0) * 1000),
                result_bytes=len(json.dumps(payload)),
            )

        await self._write_cache(ctx, url, payload)
        payload = self._truncate(payload, max_chars)
        return ToolResult(
            content=payload,
            duration_ms=int((time.monotonic() - t0) * 1000),
            result_bytes=len(json.dumps(payload)),
        )

    # ----------------------------- cache --------------------------------- #

    def _cache_path(self, ctx: ToolCtx, url: str) -> Path | None:
        if ctx.session_id is None:
            return None
        return (
            self._cfg.session_artifact_dir(ctx.session_id)
            / "papers"
            / f"{url_hash(url)}.json"
        )

    async def _read_cache(self, ctx: ToolCtx, url: str) -> dict[str, Any] | None:
        p = self._cache_path(ctx, url)
        if p is None or not p.exists():
            return None

        def _do() -> dict[str, Any] | None:
            try:
                data = json.loads(p.read_text())
            except Exception:
                return None
            if not isinstance(data, dict) or not (data.get("text") or "").strip():
                return None
            raw_text = str(data["text"])
            if _is_challenge_stub(raw_text, int(data.get("status") or 200)):
                return None
            data["text"] = _add_line_numbers(raw_text)
            return data

        return await asyncio.to_thread(_do)

    async def _write_cache(
        self, ctx: ToolCtx, url: str, payload: dict[str, Any]
    ) -> None:
        p = self._cache_path(ctx, url)
        if p is None:
            return

        def _do() -> None:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(p.suffix + ".tmp")
            tmp.write_text(json.dumps(payload, default=str, ensure_ascii=False))
            tmp.replace(p)

        await asyncio.to_thread(_do)

    @staticmethod
    def _truncate(payload: dict[str, Any], max_chars: int) -> dict[str, Any]:
        text = payload.get("text") or ""
        if len(text) > max_chars:
            payload = {**payload, "text": text[:max_chars], "truncated": True}
        return payload


# --------------------------------------------------------------------------- #
# Extractors (sync; run via to_thread)


def _extract_html(html: str, url: str) -> tuple[str, str | None]:
    import trafilatura

    extracted = trafilatura.extract(
        html, url=url, include_comments=False, include_tables=True
    )
    if not (extracted and extracted.strip()):
        extracted = trafilatura.extract(
            html,
            url=url,
            include_comments=False,
            include_tables=True,
            favor_recall=True,
        )
    title = None
    md = trafilatura.metadata.extract_metadata(html)
    if md:
        title = md.title
    return extracted or "", title


def _extract_pdf(data: bytes) -> str:
    import pypdf

    reader = pypdf.PdfReader(BytesIO(data))
    parts = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            parts.append("")
    return "\n\n".join(parts)


def _parse_pubmed_article_xml(xml_str: str) -> tuple[str, str | None, str | None]:
    """Parse NCBI E-utilities PubMed XML into `(text, title, pmcid)`."""
    root = ET.fromstring(xml_str)
    art = root.find(".//PubmedArticle")
    if art is None:
        return "", None, None
    pmid = (art.findtext(".//PMID") or "").strip()
    title_el = art.find(".//ArticleTitle")
    title = "".join(title_el.itertext()).strip() if title_el is not None else ""
    journal = (art.findtext(".//Journal/Title") or "").strip()
    year = (
        art.findtext(".//PubDate/Year")
        or art.findtext(".//PubDate/MedlineDate")
        or ""
    ).strip()
    authors: list[str] = []
    for au in art.findall(".//Author")[:10]:
        last = (au.findtext("LastName") or "").strip()
        init = (au.findtext("Initials") or "").strip()
        if last:
            authors.append(f"{last} {init}".strip())

    doi: str | None = None
    pmcid: str | None = None
    for aid in art.findall(".//ArticleId"):
        id_type = (aid.get("IdType") or "").lower()
        val = (aid.text or "").strip()
        if id_type == "doi" and val:
            doi = val
        elif id_type == "pmc" and val:
            pmcid = val if val.upper().startswith("PMC") else f"PMC{val}"

    lines: list[str] = []
    if title:
        lines.append(f"Title: {title}")
    meta_bits: list[str] = []
    if journal:
        meta_bits.append(f"Journal: {journal}")
    if year:
        meta_bits.append(f"Year: {year[:4]}")
    if pmid:
        meta_bits.append(f"PMID: {pmid}")
    if pmcid:
        meta_bits.append(f"PMCID: {pmcid}")
    if doi:
        meta_bits.append(f"DOI: {doi}")
    if meta_bits:
        lines.append(" | ".join(meta_bits))
    if authors:
        lines.append(f"Authors: {', '.join(authors)}")

    for at in art.findall(".//Abstract/AbstractText"):
        label = (at.get("Label") or "").strip()
        txt = " ".join("".join(at.itertext()).split()).strip()
        if txt:
            lines.append(f"{label}: {txt}" if label else txt)

    return "\n".join(lines), (title or None), pmcid


def _local_tag(el: ET.Element) -> str:
    tag = el.tag
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) and "}" in tag else str(tag)


def _parse_jats_fulltext_xml(xml_str: str) -> tuple[str, str | None]:
    """Parse Europe PMC / PMC JATS full-text XML into `(text, title)`."""
    root = ET.fromstring(xml_str)
    title = ""
    journal = ""
    for el in root.iter():
        lt = _local_tag(el)
        if lt == "article-title" and not title:
            title = " ".join("".join(el.itertext()).split()).strip()
        elif lt == "journal-title" and not journal:
            journal = " ".join("".join(el.itertext()).split()).strip()
        if title and journal:
            break

    lines: list[str] = []
    if title:
        lines.append(f"Title: {title}")
    if journal:
        lines.append(f"Journal: {journal}")

    for el in root.iter():
        if _local_tag(el) == "abstract":
            lines.append("Abstract")
            p_found = False
            for sub in el.iter():
                if _local_tag(sub) == "p":
                    txt = " ".join("".join(sub.itertext()).split()).strip()
                    if txt:
                        lines.append(txt)
                        p_found = True
            if not p_found:
                txt = " ".join("".join(el.itertext()).split()).strip()
                if txt:
                    lines.append(txt)
            break

    skip_containers = {"table-wrap", "fig", "fn-group", "ref-list", "back"}

    def _walk_body(node: ET.Element) -> None:
        for child in list(node):
            lt = _local_tag(child)
            if lt in skip_containers:
                continue
            if lt in {"title", "p"}:
                txt = " ".join("".join(child.itertext()).split()).strip()
                if txt:
                    lines.append(txt)
            else:
                _walk_body(child)

    for el in root.iter():
        if _local_tag(el) == "body":
            _walk_body(el)
            break

    return "\n".join(lines), (title or None)


async def _try_biomed_api_fallback(
    url: str, *, timeout: float, headers: dict[str, str]
) -> tuple[str, str | None, str, int, int] | None:
    """Cookie-free, keyless fallback for PubMed, PMC, and Europe PMC article
    URLs when their web frontends serve AWS WAF cookie challenges (HTTP 203) or
    JavaScript SPA shells."""
    pmid, pmcid = _parse_biomed_url(url)
    if not pmid and not pmcid:
        return None

    refuse_jar = _make_cookie_jar("refuse_all", "")
    pubmed_text = ""
    pubmed_title: str | None = None
    pubmed_bytes = 0

    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            headers=headers,
            cookies=httpx.Cookies(refuse_jar),
        ) as client:
            if pmid:
                r = await client.get(
                    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
                    params={
                        "db": "pubmed",
                        "id": pmid,
                        "rettype": "abstract",
                        "retmode": "xml",
                    },
                )
                if r.status_code == 200 and r.text.strip():
                    pubmed_bytes = len(r.text.encode("utf-8"))
                    pubmed_text, pubmed_title, discovered_pmcid = (
                        await asyncio.to_thread(_parse_pubmed_article_xml, r.text)
                    )
                    if not pmcid and discovered_pmcid:
                        pmcid = discovered_pmcid

            if pmcid:
                ft_url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
                r_ft = await client.get(ft_url)
                if r_ft.status_code == 200 and "<article" in r_ft.text:
                    ft_text, ft_title = await asyncio.to_thread(
                        _parse_jats_fulltext_xml, r_ft.text
                    )
                    if ft_text.strip():
                        return (
                            ft_text,
                            ft_title or pubmed_title,
                            "application/xml",
                            200,
                            len(r_ft.text.encode("utf-8")),
                        )
    except Exception:
        pass

    if pubmed_text.strip():
        return (pubmed_text, pubmed_title, "application/xml", 200, pubmed_bytes)
    return None
