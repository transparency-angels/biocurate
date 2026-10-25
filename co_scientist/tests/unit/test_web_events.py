"""The session SSE stream carries timeline messages live (SQLite backend).

httpx's ASGITransport buffers the whole body, so an endless SSE response is
driven with a raw ASGI harness that reads chunks as they are sent and can
simulate the client disconnecting.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any

import pytest
from pymongo.errors import PyMongoError
from structlog.testing import capture_logs

from co_scientist import timeline
from co_scientist.config import Config
from co_scientist.orchestrator.events import GLOBAL_BUS
from co_scientist.storage import db as db_mod
from co_scientist.storage import watch as watch_mod
from co_scientist.storage.sqlite import watch as sqlite_watch
from co_scientist.web.app import create_app

from .test_web_api import _make_session

_PAYLOAD_KEYS = {"seq", "ts", "role", "agent", "kind", "title", "body_markdown", "refs"}


@pytest.fixture(autouse=True)
def _fast_poll(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sqlite_watch, "POLL_INTERVAL_S", 0.02)


class _SSE:
    """Run one GET against the app and expose the SSE events it sends."""

    def __init__(self, cfg: Config, path: str, headers: dict[str, str] | None = None):
        self._app = create_app(cfg)
        path, _, qs = path.partition("?")
        self._scope = {
            "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
            "method": "GET", "scheme": "http", "path": path, "raw_path": path.encode(),
            "query_string": qs.encode(), "root_path": "", "server": ("test", 80),
            "client": ("127.0.0.1", 1),
            "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
        }
        self._disconnect = asyncio.Event()
        self._requested = False
        self._chunks: asyncio.Queue[bytes] = asyncio.Queue()
        self._buf = ""
        self._task: asyncio.Task | None = None

    async def _receive(self) -> dict[str, Any]:
        if not self._requested:
            self._requested = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await self._disconnect.wait()
        return {"type": "http.disconnect"}

    async def _send(self, msg: dict[str, Any]) -> None:
        if msg["type"] == "http.response.body":
            self._chunks.put_nowait(msg.get("body", b""))

    async def __aenter__(self) -> _SSE:
        self._task = asyncio.create_task(self._app(self._scope, self._receive, self._send))
        return self

    async def disconnect(self) -> None:
        self._disconnect.set()
        assert self._task is not None
        await asyncio.wait_for(self._task, timeout=5)

    async def __aexit__(self, *exc: object) -> None:
        if not self._disconnect.is_set():
            await self.disconnect()

    async def next_event(self, timeout: float = 5.0) -> dict[str, str]:
        """The next non-comment SSE event as {field: value}."""
        while True:
            self._buf = self._buf.replace("\r\n", "\n")
            if "\n\n" in self._buf:
                block, self._buf = self._buf.split("\n\n", 1)
                ev: dict[str, str] = {}
                for line in block.split("\n"):
                    if not line or line.startswith(":"):
                        continue
                    key, _, val = line.partition(":")
                    ev[key] = val[1:] if val.startswith(" ") else val
                if ev:
                    return ev
                continue
            chunk = await asyncio.wait_for(self._chunks.get(), timeout=timeout)
            self._buf += chunk.decode()

    async def timeline_events(self, n: int, timeout: float = 5.0) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        while len(out) < n:
            ev = await self.next_event(timeout)
            if ev.get("event") == "timeline_message":
                out.append(ev)
        return out

    async def drain(self, seconds: float) -> list[dict[str, str]]:
        """Every event that arrives within `seconds`."""
        out: list[dict[str, str]] = []
        with contextlib.suppress(TimeoutError):
            async with asyncio.timeout(seconds):
                while True:
                    out.append(await self.next_event(timeout=seconds))
        return out


async def _post(cfg: Config, sid: str, *titles: str) -> None:
    conn = await db_mod.connect(cfg)
    try:
        for t in titles:
            await timeline.post(conn, sid, kind="note", title=t)
    finally:
        await conn.close()


def _seqs(events: list[dict[str, str]]) -> list[int]:
    return [json.loads(e["data"])["seq"] for e in events if e.get("event") == "timeline_message"]


async def test_events_stream_includes_timeline_messages(tmp_cfg) -> None:
    sid = await _make_session(tmp_cfg)
    await _post(tmp_cfg, sid, "m1", "m2", "m3")
    async with _SSE(tmp_cfg, f"/api/sessions/{sid}/events") as sse:
        evs = await sse.timeline_events(3)
    assert [e["id"] for e in evs] == ["1", "2", "3"]
    datas = [json.loads(e["data"]) for e in evs]
    assert [d["title"] for d in datas] == ["m1", "m2", "m3"]
    assert all(set(d) == _PAYLOAD_KEYS for d in datas)


async def test_events_stream_resumes_timeline_after_seq(tmp_cfg) -> None:
    sid = await _make_session(tmp_cfg)
    await _post(tmp_cfg, sid, "m1", "m2", "m3")
    path = f"/api/sessions/{sid}/events"
    async with _SSE(tmp_cfg, path, {"Last-Event-ID": "2"}) as sse:
        [first] = await sse.timeline_events(1)
        assert first["id"] == "3"
        assert GLOBAL_BUS.subscriber_count(sid) == 1
        # Posted in-process: arrives on the bus AND through the watcher.
        await _post(tmp_cfg, sid, "m4")
        [fourth] = await sse.timeline_events(1)
        assert fourth["id"] == "4"
        rest = await sse.drain(0.3)
    assert _seqs(rest) == []


async def test_start_is_max_of_query_and_header_and_bad_values_mean_zero(tmp_cfg) -> None:
    sid = await _make_session(tmp_cfg)
    await _post(tmp_cfg, sid, "m1", "m2", "m3")
    path = f"/api/sessions/{sid}/events"
    cases = [
        (f"{path}?after_seq=1", {"Last-Event-ID": "2"}, ["3"]),
        (f"{path}?after_seq=2", {"Last-Event-ID": "1"}, ["3"]),
        (f"{path}?after_seq=1", {"Last-Event-ID": "x"}, ["2", "3"]),
        (f"{path}?after_seq=abc", {"Last-Event-ID": "2"}, ["3"]),
        (f"{path}?after_seq=-5", {"Last-Event-ID": "-1"}, ["1", "2", "3"]),
        (f"{path}?after_seq=abc", {"Last-Event-ID": "x"}, ["1", "2", "3"]),
    ]
    for url, headers, want in cases:
        async with _SSE(tmp_cfg, url, headers) as sse:
            got = [e["id"] for e in await sse.timeline_events(len(want))]
            got += [str(s) for s in _seqs(await sse.drain(0.1))]
        assert got == want, (url, headers)


async def test_watcher_failure_logs_type_only_and_bus_keeps_flowing(
    tmp_cfg, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "mongodb+srv://user:hunter2@cluster0.example.net"

    async def boom(conn, session_id, after_seq):
        raise PyMongoError(f"connection refused {secret}")
        yield  # pragma: no cover - makes this an async generator

    monkeypatch.setattr(watch_mod, "timeline_after", boom)
    sid = await _make_session(tmp_cfg)
    with capture_logs() as logs:
        async with _SSE(tmp_cfg, f"/api/sessions/{sid}/events") as sse:
            for _ in range(100):
                if GLOBAL_BUS.subscriber_count(sid) and any(
                    e.get("event") == "timeline_watch_failed" for e in logs
                ):
                    break
                await asyncio.sleep(0.01)
            await GLOBAL_BUS.publish(sid, "match_complete", {"x": 1})
            ev = await sse.next_event()
    assert ev["event"] == "match_complete"
    failed = [e for e in logs if e.get("event") == "timeline_watch_failed"]
    assert failed and failed[0]["err_type"] == "PyMongoError"
    assert "hunter2" not in repr(logs)


async def test_watcher_ending_normally_is_logged(
    tmp_cfg, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def ends(conn, session_id, after_seq):
        return
        yield  # pragma: no cover

    monkeypatch.setattr(watch_mod, "timeline_after", ends)
    sid = await _make_session(tmp_cfg)
    with capture_logs() as logs:
        async with _SSE(tmp_cfg, f"/api/sessions/{sid}/events"):
            for _ in range(100):
                if any(e.get("event") == "timeline_watch_ended" for e in logs):
                    break
                await asyncio.sleep(0.01)
    ended = [e for e in logs if e.get("event") == "timeline_watch_ended"]
    assert ended and ended[0]["session_id"] == sid
    assert not any(e.get("event") == "timeline_watch_failed" for e in logs)


async def test_events_stream_still_carries_other_bus_events(tmp_cfg) -> None:
    sid = await _make_session(tmp_cfg)
    async with _SSE(tmp_cfg, f"/api/sessions/{sid}/events") as sse:
        for _ in range(100):
            if GLOBAL_BUS.subscriber_count(sid):
                break
            await asyncio.sleep(0.01)
        await GLOBAL_BUS.publish(sid, "match_complete", {"x": 1})
        ev = await sse.next_event()
    assert ev["event"] == "match_complete"
    assert json.loads(ev["data"])["payload"] == {"x": 1}


async def test_events_stream_carries_hypothesis_lifecycle_and_match_events(tmp_cfg) -> None:
    sid = await _make_session(tmp_cfg)
    async with _SSE(tmp_cfg, f"/api/sessions/{sid}/events") as sse:
        for _ in range(100):
            if GLOBAL_BUS.subscriber_count(sid):
                break
            await asyncio.sleep(0.01)
        await GLOBAL_BUS.publish(sid, "hypothesis_generated", {"hypothesis_id": "hyp_1", "state": "draft"})
        ev1 = await sse.next_event()
        assert ev1["event"] == "hypothesis_generated"
        assert json.loads(ev1["data"])["payload"]["hypothesis_id"] == "hyp_1"

        await GLOBAL_BUS.publish(sid, "hypothesis_reviewed", {"hypothesis_id": "hyp_1", "state": "reviewed"})
        ev2 = await sse.next_event()
        assert ev2["event"] == "hypothesis_reviewed"
        assert json.loads(ev2["data"])["payload"]["state"] == "reviewed"

        await GLOBAL_BUS.publish(sid, "match_completed", {"winner_id": "hyp_1", "loser_id": "hyp_2"})
        ev3 = await sse.next_event()
        assert ev3["event"] == "match_completed"
        assert json.loads(ev3["data"])["payload"]["winner_id"] == "hyp_1"


async def test_disconnect_closes_watcher_bus_and_connection(
    tmp_cfg, monkeypatch: pytest.MonkeyPatch
) -> None:
    sid = await _make_session(tmp_cfg)
    await _post(tmp_cfg, sid, "m1")

    closed_gens: list[bool] = []
    real_after = watch_mod.timeline_after

    async def spy_after(conn, session_id, after_seq):
        try:
            async with contextlib.aclosing(real_after(conn, session_id, after_seq)) as gen:
                async for m in gen:
                    yield m
        finally:
            closed_gens.append(True)

    monkeypatch.setattr(watch_mod, "timeline_after", spy_after)

    opened: list[Any] = []
    closed: list[Any] = []
    real_connect = db_mod.connect

    async def spy_connect(cfg):
        c = await real_connect(cfg)
        real_close = c.close

        async def close():
            closed.append(c)
            await real_close()

        c.close = close
        opened.append(c)
        return c

    monkeypatch.setattr(db_mod, "connect", spy_connect)

    sse = _SSE(tmp_cfg, f"/api/sessions/{sid}/events")
    async with sse:
        await sse.timeline_events(1)
        assert GLOBAL_BUS.subscriber_count(sid) == 1
        await sse.disconnect()
    assert closed_gens == [True]
    assert GLOBAL_BUS.subscriber_count(sid) == 0
    assert opened and all(c in closed for c in opened)
