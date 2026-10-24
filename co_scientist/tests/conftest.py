"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio

from co_scientist.config import Config, RunCfg, Secrets, StorageCfg
from co_scientist.storage import db as db_mod


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
