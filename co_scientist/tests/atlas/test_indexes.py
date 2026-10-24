from __future__ import annotations

from co_scientist.storage.atlas.indexes import ensure_indexes


async def test_ensure_indexes_is_idempotent(atlas_conn, atlas_cfg):
    await ensure_indexes(atlas_conn, atlas_cfg)
    info = await atlas_conn.coll("tasks").index_information()
    idem = [v for v in info.values() if v["key"] == [("idempotency_key", 1)]]
    assert idem and idem[0].get("unique") is True
