"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio

from co_scientist.config import Config, RunCfg, Secrets, StorageCfg
from co_scientist.storage import db as db_mod
from co_scientist.tests import atlas_support


@pytest.fixture(autouse=True)
def _isolate_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the developer's real `.env` and shell secrets out of every test.

    `Secrets` is a BaseSettings with `env_file=".env"`, and `make_embedder`
    also reads `os.environ` directly, so both are neutralised. Tests that need
    real credentials (tests/atlas) opt back in by building `Secrets` with an
    explicit `_env_file`.
    """
    monkeypatch.setitem(Secrets.model_config, "env_file", None)
    for name in Secrets.model_fields:
        monkeypatch.delenv(name, raising=False)


@pytest_asyncio.fixture
async def tmp_cfg(tmp_path: Path) -> Config:
    """A Config rooted at a fresh tmp dir, with init_db applied."""
    cfg = Config(
        run=RunCfg(),
        storage=StorageCfg(data_dir=str(tmp_path)),
    )
    (tmp_path / "artifacts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "vectors").mkdir(parents=True, exist_ok=True)
    (tmp_path / "logs").mkdir(parents=True, exist_ok=True)
    await db_mod.init_db(cfg)
    return cfg


@pytest_asyncio.fixture
async def conn(tmp_cfg: Config):
    c = await db_mod.connect(tmp_cfg)
    try:
        yield c
    finally:
        await c.close()


@pytest_asyncio.fixture(params=["sqlite", "atlas"])
async def any_conn(request: pytest.FixtureRequest, tmp_cfg: Config):
    """A connection on each backend; the atlas param needs CO_SCI_ATLAS_TESTS=1."""
    if request.param == "sqlite":
        c = await db_mod.connect(tmp_cfg)
        try:
            yield c
        finally:
            await c.close()
        return
    if not atlas_support.ENABLED:
        pytest.skip("set CO_SCI_ATLAS_TESTS=1 to run live Atlas tests")
    from co_scientist.storage.atlas.client import connect_atlas
    from co_scientist.storage.atlas.indexes import ensure_indexes

    cfg = atlas_support.make_atlas_cfg()
    c = await connect_atlas(cfg)
    try:
        await ensure_indexes(c, cfg, search=False)
        yield c
    finally:
        await atlas_support.drop_prefixed(c.db, c.prefix)
