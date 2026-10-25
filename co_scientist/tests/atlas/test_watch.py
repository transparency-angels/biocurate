"""Live-Atlas: the timeline watcher follows a change stream across connections."""

from __future__ import annotations

import asyncio
import contextlib

import certifi
from pymongo import AsyncMongoClient

from co_scientist import ids
from co_scientist.storage import watch
from co_scientist.storage.atlas.client import AtlasConn
from co_scientist.storage.repos import timeline as timeline_repo


async def _append(conn, sid: str, title: str):
    return await timeline_repo.append(
        conn, sid, role="system", agent=None, kind="note", title=title,
        body_markdown="", refs=[],
    )


async def test_watch_delivers_inserts_from_another_connection(atlas_conn, atlas_cfg):
    # A separate client: connect_atlas would hand back the cached, shared one.
    other_client = AsyncMongoClient(
        atlas_cfg.secrets.MONGODB_URI, tz_aware=True, tlsCAFile=certifi.where()
    )
    other = AtlasConn(
        client=other_client, db=other_client[atlas_conn.db.name], prefix=atlas_conn.prefix
    )
    sid = ids.session_id()
    try:
        await _append(other, sid, "backlog")
        async with contextlib.aclosing(watch.timeline_after(atlas_conn, sid, 0)) as gen:
            first = await asyncio.wait_for(anext(gen), timeout=10)
            assert (first.seq, first.title) == (1, "backlog")
            # The stream was opened before the backlog read, so this insert is caught.
            await _append(other, sid, "live")
            second = await asyncio.wait_for(anext(gen), timeout=5)
            assert (second.seq, second.title) == (2, "live")
            assert second.session_id == sid
    finally:
        await other_client.close()


async def test_watch_skips_backlog_and_other_sessions(atlas_conn):
    sid, noise = ids.session_id(), ids.session_id()
    for t in ("a", "b", "c"):
        await _append(atlas_conn, sid, t)
    async with contextlib.aclosing(watch.timeline_after(atlas_conn, sid, 2)) as gen:
        got = await asyncio.wait_for(anext(gen), timeout=10)
        assert got.seq == 3
        await _append(atlas_conn, noise, "other session")
        await _append(atlas_conn, sid, "d")
        nxt = await asyncio.wait_for(anext(gen), timeout=5)
        assert (nxt.seq, nxt.title, nxt.session_id) == (4, "d", sid)
