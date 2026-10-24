"""Fixtures for live-Atlas tests. Skipped unless CO_SCI_ATLAS_TESTS=1."""

from __future__ import annotations

import os
import re

import pytest
import pytest_asyncio
from ulid import ULID

from co_scientist.config import Config, Secrets, StorageCfg
from co_scientist.storage.atlas.client import connect_atlas
from co_scientist.storage.atlas.indexes import ensure_indexes

ENABLED = os.environ.get("CO_SCI_ATLAS_TESTS") == "1"
_SAFE_PREFIX = re.compile(r"^t[0-9a-z]{10,}_$")


def pytest_collection_modifyitems(config, items):
    if ENABLED:
        return
    skip = pytest.mark.skip(reason="set CO_SCI_ATLAS_TESTS=1 to run live Atlas tests")
    here = os.path.dirname(__file__)
    for item in items:
        if str(item.path).startswith(here + os.sep):
            item.add_marker(skip)


async def drop_prefixed(db, prefix: str) -> list[str]:
    """Drop the collections whose names start with a per-test prefix.

    Refuses anything that does not look like a generated test prefix, so a bad
    argument can never touch real collections. Never drops the database.
    """
    if not _SAFE_PREFIX.fullmatch(prefix or ""):
        raise ValueError(f"refusing to drop with unsafe prefix {prefix!r}")
    dropped = []
    for name in await db.list_collection_names():
        if name.startswith(prefix):
            await db.drop_collection(name)
            dropped.append(name)
    return dropped


@pytest.fixture
def atlas_cfg() -> Config:
    # Opt back in to the real .env, which the autouse isolation fixture hides.
    secrets = Secrets(_env_file=".env")
    prefix = f"t{str(ULID()).lower()}_"
    return Config(
        storage=StorageCfg(backend="atlas", atlas_prefix=prefix),
        secrets=secrets,
    )


@pytest_asyncio.fixture
async def atlas_conn(atlas_cfg: Config):
    conn = await connect_atlas(atlas_cfg)
    try:
        await ensure_indexes(conn, atlas_cfg)
        yield conn
    finally:
        await drop_prefixed(conn.db, conn.prefix)
