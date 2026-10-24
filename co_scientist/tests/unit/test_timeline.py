"""Timeline repo and best-effort poster."""

from __future__ import annotations

import asyncio
import contextlib

from co_scientist import timeline
from co_scientist.orchestrator.events import GLOBAL_BUS
from co_scientist.storage.repos import timeline as repo


async def _append(conn, sid, i):
    return await repo.append(
        conn, sid, role="system", agent=None, kind="k", title=f"t{i}", body_markdown="", refs=[]
    )


async def test_timeline_append_and_list_after_seq(any_conn):
    a = await repo.append(
        any_conn, "s1", role="assistant", agent="gen", kind="x", title="A",
        body_markdown="**b**", refs=["h1"],
    )
    await _append(any_conn, "s1", 2)
    await _append(any_conn, "s2", 1)
    assert a.seq == 1 and a.ts.tzinfo is not None and a.refs == ["h1"]
    rows = await repo.list_for_session(any_conn, "s1")
    assert [m.seq for m in rows] == [1, 2]
    assert rows[0].agent == "gen" and rows[0].body_markdown == "**b**"
    assert [m.seq for m in await repo.list_for_session(any_conn, "s1", after_seq=1)] == [2]
    assert len(await repo.list_for_session(any_conn, "s1", limit=1)) == 1


async def test_timeline_concurrent_appends_unique_seq(any_conn):
    msgs = await asyncio.gather(*[_append(any_conn, "sc", i) for i in range(20)])
    assert sorted(m.seq for m in msgs) == list(range(1, 21))


async def test_timeline_post_never_raises(monkeypatch):
    calls = []

    async def boom(*a, **k):
        raise RuntimeError("secret detail")

    class Log:
        def warning(self, event, **kw):
            calls.append((event, kw))

    monkeypatch.setattr(timeline.timeline_repo, "append", boom)
    monkeypatch.setattr(timeline, "log", Log())
    assert await timeline.post(object(), "s", kind="k", title="t") is None
    assert calls == [
        ("timeline_post_failed", {"session_id": "s", "kind": "k", "err_type": "RuntimeError"})
    ]


async def test_timeline_post_publishes_bus_event(any_conn):
    async with contextlib.aclosing(GLOBAL_BUS.subscribe("sb")) as sub:
        task = asyncio.ensure_future(sub.__anext__())
        await asyncio.sleep(0)
        await timeline.post(any_conn, "sb", kind="k", title="T", body="B", agent="a", refs=["r"])
        ev = await asyncio.wait_for(task, 2)
    assert ev.name == "timeline_message"
    p = ev.payload
    assert set(p) == {"seq", "ts", "role", "agent", "kind", "title", "body_markdown", "refs"}
    assert p["seq"] == 1 and isinstance(p["ts"], int) and p["role"] == "assistant"
    assert p["body_markdown"] == "B" and p["refs"] == ["r"] and p["agent"] == "a"
    assert [m.seq for m in await repo.list_for_session(any_conn, "sb")] == [1]
