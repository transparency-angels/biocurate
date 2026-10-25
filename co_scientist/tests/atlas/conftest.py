"""Fixtures for live-Atlas tests. Skipped unless CO_SCI_ATLAS_TESTS=1."""

from __future__ import annotations

import os

import pytest
import pytest_asyncio

from co_scientist.config import Config
from co_scientist.storage.atlas.client import connect_atlas
from co_scientist.storage.atlas.indexes import ensure_indexes
from co_scientist.tests.atlas_support import (
    ENABLED,
    SEARCH_ENABLED,
    drop_prefixed,
    make_atlas_cfg,
)


def pytest_collection_modifyitems(config, items):
    if ENABLED:
        if not SEARCH_ENABLED:
            slow = pytest.mark.skip(
                reason="waits for search index builds; set CO_SCI_ATLAS_SEARCH_TESTS=1",
            )
            for item in items:
                if item.get_closest_marker("atlas_search"):
                    item.add_marker(slow)
        return
    skip = pytest.mark.skip(reason="set CO_SCI_ATLAS_TESTS=1 to run live Atlas tests")
    here = os.path.dirname(__file__)
    for item in items:
        if str(item.path).startswith(here + os.sep):
            item.add_marker(skip)


@pytest.fixture
def atlas_cfg() -> Config:
    return make_atlas_cfg()


@pytest_asyncio.fixture
async def atlas_conn(request: pytest.FixtureRequest, atlas_cfg: Config):
    conn = await connect_atlas(atlas_cfg)
    try:
        search = request.node.get_closest_marker("atlas_search") is not None
        await ensure_indexes(conn, atlas_cfg, search=search)
        yield conn
    finally:
        await drop_prefixed(conn.db, conn.prefix)
