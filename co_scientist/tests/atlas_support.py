"""Helpers shared by the live-Atlas tests and the `any_conn` fixture."""

from __future__ import annotations

import os
import re

from ulid import ULID

from co_scientist.config import Config, Secrets, StorageCfg

ENABLED = os.environ.get("CO_SCI_ATLAS_TESTS") == "1"
# Tests that wait for Atlas Search / Vector Search index builds (minutes each).
SEARCH_ENABLED = ENABLED and os.environ.get("CO_SCI_ATLAS_SEARCH_TESTS") == "1"
_SAFE_PREFIX = re.compile(r"^t[0-9a-z]{10,}_$")


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


def make_atlas_cfg() -> Config:
    """Atlas config with a fresh per-test prefix and the real `.env` secrets.

    Opts back in to `.env`, which the autouse isolation fixture hides.
    """
    secrets = Secrets(_env_file=".env")
    prefix = f"t{str(ULID()).lower()}_"
    return Config(
        storage=StorageCfg(backend="atlas", atlas_prefix=prefix),
        secrets=secrets,
    )
