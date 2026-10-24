"""SSRF guard tests for web_fetch.

We can't easily exercise the live httpx path in a unit test, but we *can*
verify that the SSRF guard rejects private/loopback/metadata-service hosts
before the network call.
"""

from __future__ import annotations

import pytest

from co_scientist.config import Config
from co_scientist.tools.base import ToolCtx
from co_scientist.tools.web_fetch import (
    WebFetchTool,
    _add_line_numbers,
    _extract_meta_refresh_url,
    _is_challenge_stub,
    _is_private_ip,
    _make_cookie_jar,
    _parse_biomed_url,
    _request_headers,
)


def test_private_ip_helper_blocks_loopback() -> None:
    assert _is_private_ip("127.0.0.1") is True
    assert _is_private_ip("localhost") is True


def test_private_ip_helper_blocks_link_local_metadata() -> None:
    # AWS / GCP metadata service
    assert _is_private_ip("169.254.169.254") is True


def test_private_ip_helper_blocks_rfc1918() -> None:
    assert _is_private_ip("10.0.0.1") is True
    assert _is_private_ip("192.168.1.1") is True
    assert _is_private_ip("172.16.0.1") is True


def test_private_ip_helper_allows_public() -> None:
    # 1.1.1.1 (Cloudflare DNS) is a stable public address
    assert _is_private_ip("1.1.1.1") is False


@pytest.mark.asyncio
async def test_web_fetch_rejects_loopback_url() -> None:
    tool = WebFetchTool(Config())
    res = await tool.call({"url": "http://127.0.0.1/admin"}, ToolCtx(cfg=Config(), db=None))
    assert res.is_error
    assert "private" in (res.error_message or "").lower()


@pytest.mark.asyncio
async def test_web_fetch_rejects_metadata_url() -> None:
    tool = WebFetchTool(Config())
    res = await tool.call(
        {"url": "http://169.254.169.254/latest/meta-data/"},
        ToolCtx(cfg=Config(), db=None),
    )
    assert res.is_error
    assert "private" in (res.error_message or "").lower()


@pytest.mark.asyncio
async def test_web_fetch_rejects_unsupported_scheme() -> None:
    tool = WebFetchTool(Config())
    res = await tool.call({"url": "file:///etc/passwd"}, ToolCtx(cfg=Config(), db=None))
    assert res.is_error


def test_default_cookie_policy_is_refuse_all() -> None:
    cfg = Config()
    assert cfg.web_fetch.cookie_policy == "refuse_all"
    headers = _request_headers(cfg.web_fetch.user_agent)
    assert headers["DNT"] == "1"
    assert headers["Sec-GPC"] == "1"


def test_refuse_all_cookie_jar_blocks_every_cookie() -> None:
    import email.message
    import urllib.request

    class _DummyResp:
        def __init__(self, set_cookies: list[str]) -> None:
            self.msg = email.message.Message()
            for sc in set_cookies:
                self.msg.add_header("Set-Cookie", sc)

        def info(self) -> email.message.Message:
            return self.msg

    jar = _make_cookie_jar("refuse_all", "www.mdpi.com")
    req = urllib.request.Request("https://www.mdpi.com/1422-0067/27/14/6513")
    resp = _DummyResp(
        [
            "JSESSIONID=abc123; Path=/; Secure; HttpOnly",
            "ak_bmsc=def456; Domain=.mdpi.com; Path=/",
            "_ga=GA1.1.12345; Domain=.mdpi.com; Path=/",
        ]
    )
    jar.extract_cookies(resp, req)  # type: ignore[arg-type]
    assert len(jar) == 0


def test_essential_only_cookie_jar_blocks_tracking_and_third_party_cookies() -> None:
    import email.message
    import urllib.request

    class _DummyResp:
        def __init__(self, set_cookies: list[str]) -> None:
            self.msg = email.message.Message()
            for sc in set_cookies:
                self.msg.add_header("Set-Cookie", sc)

        def info(self) -> email.message.Message:
            return self.msg

    jar = _make_cookie_jar("essential_only", "www.mdpi.com")
    req = urllib.request.Request("https://www.mdpi.com/1422-0067/27/14/6513")
    resp = _DummyResp(
        [
            "ak_bmsc=bot_token; Domain=.mdpi.com; Path=/",
            "JSESSIONID=sess_1; Path=/; Secure; HttpOnly",
            "_ga=GA1.1.12345; Domain=.mdpi.com; Path=/",
            "_gid=GA1.2.67890; Domain=.mdpi.com; Path=/",
            "_fbp=fb.1.9999; Domain=.mdpi.com; Path=/",
            "OptanonConsent=isGpcEnabled=1; Domain=.mdpi.com; Path=/",
            "cookieconsent_status=dismiss; Domain=.mdpi.com; Path=/",
            "ad_tracker=xyz; Domain=.mdpi.com; Path=/",
            "third_party_sess=1; Domain=.doubleclick.net; Path=/",
        ]
    )
    jar.extract_cookies(resp, req)  # type: ignore[arg-type]
    kept = {c.name for c in jar}
    assert kept == {"ak_bmsc", "JSESSIONID"}


def test_extract_meta_refresh_url() -> None:
    html = (
        '<html><head><meta http-equiv="refresh" '
        'content="0; url=/1422-0067/27/14/6513?cookie_check=1"></head><body></body></html>'
    )
    assert (
        _extract_meta_refresh_url(html, "https://www.mdpi.com/1422-0067/27/14/6513")
        == "https://www.mdpi.com/1422-0067/27/14/6513?cookie_check=1"
    )


@pytest.mark.asyncio
async def test_web_fetch_ignores_poisoned_empty_cache(tmp_path) -> None:
    import json

    from co_scientist.ids import url_hash

    cfg = Config()
    cfg.storage.data_dir = str(tmp_path)
    tool = WebFetchTool(cfg)
    ctx = ToolCtx(cfg=cfg, db=None, session_id="ses_test")
    url = "https://www.mdpi.com/1422-0067/27/14/6513"

    cache_file = tmp_path / "artifacts" / "ses_test" / "papers" / f"{url_hash(url)}.json"
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(
        json.dumps(
            {
                "url": url,
                "title": None,
                "text": "",
                "content_type": "text/html",
                "status": 200,
                "bytes": 2211,
            }
        )
    )
    assert await tool._read_cache(ctx, url) is None


@pytest.mark.asyncio
async def test_web_fetch_does_not_cache_empty_extraction(tmp_path, monkeypatch) -> None:
    import httpx

    from co_scientist.ids import url_hash

    cfg = Config()
    cfg.storage.data_dir = str(tmp_path)
    tool = WebFetchTool(cfg)
    ctx = ToolCtx(cfg=cfg, db=None, session_id="ses_empty")
    url = "https://www.mdpi.com/1422-0067/27/14/6513"

    monkeypatch.setattr("co_scientist.tools.web_fetch._is_private_ip", lambda _h: False)
    monkeypatch.setattr(
        "co_scientist.tools.web_fetch._extract_html", lambda _html, _url: ("", None)
    )

    page_url = httpx.URL(url)  # class bodies can't see the enclosing function's locals

    class _DummyStream:
        status_code = 200
        url = page_url
        headers = httpx.Headers({"content-type": "text/html"})
        history: tuple = ()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def aiter_bytes(self):
            yield b"<html><body>Please enable cookies</body></html>"

    class _DummyClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        def stream(self, method: str, target_url: str):
            return _DummyStream()

    monkeypatch.setattr("co_scientist.tools.web_fetch.httpx.AsyncClient", _DummyClient)

    res = await tool.call({"url": url}, ctx)
    assert res.is_error
    assert "empty text extracted" in (res.error_message or "")
    cache_file = tmp_path / "artifacts" / "ses_empty" / "papers" / f"{url_hash(url)}.json"
    assert not cache_file.exists()


def test_add_line_numbers_and_challenge_stub_detection() -> None:
    numbered = _add_line_numbers("First line.\nSecond line.")
    assert numbered == "[L1] First line.\n[L2] Second line."
    assert _add_line_numbers(numbered) == numbered

    assert _is_challenge_stub(
        "Enable cookies for pubmed.ncbi.nlm.nih.gov and reload this page to continue.",
        203,
    )
    assert _is_challenge_stub(
        "Enable cookies for pubmed.ncbi.nlm.nih.gov and reload this page to continue.",
        200,
    )
    assert not _is_challenge_stub("Short-chain fatty acids regulate colonic Treg cells.", 200)

    assert _parse_biomed_url("https://pubmed.ncbi.nlm.nih.gov/38565643/") == ("38565643", None)
    assert _parse_biomed_url("https://europepmc.org/article/PMC/PMC13666990") == (
        None,
        "PMC13666990",
    )


