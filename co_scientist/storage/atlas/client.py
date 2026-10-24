"""Atlas connection handle.

An `AsyncMongoClient` is bound to the event loop it first ran on, and the CLI
calls `asyncio.run` repeatedly, so clients are cached per (uri, running loop).
They are shared, which is why `AtlasConn.close()` does nothing; call
`shutdown_clients()` to really close them.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

import certifi
from pymongo import AsyncMongoClient
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.asynchronous.database import AsyncDatabase

if TYPE_CHECKING:
    from ...config import Config

_clients: dict[tuple[str, int], AsyncMongoClient] = {}


@dataclass
class AtlasConn:
    client: AsyncMongoClient
    db: AsyncDatabase
    prefix: str = ""

    def coll(self, name: str) -> AsyncCollection:
        return self.db[self.prefix + name]

    async def ensure_collection(self, name: str) -> None:
        """Create the collection if absent (search indexes need it to exist)."""
        full = self.prefix + name
        if full not in await self.db.list_collection_names():
            try:
                await self.db.create_collection(full)
            except Exception as e:  # lost a race with another creator
                if getattr(e, "code", None) != 48:  # NamespaceExists
                    raise

    async def close(self) -> None:
        """No-op: the client is shared. See `shutdown_clients`."""

    def __repr__(self) -> str:
        return f"AtlasConn(db={self.db.name!r}, prefix={self.prefix!r})"


async def connect_atlas(cfg: Config) -> AtlasConn:
    uri = cfg.secrets.MONGODB_URI
    if not uri:
        raise RuntimeError("MONGODB_URI not set")
    key = (uri, id(asyncio.get_running_loop()))
    client = _clients.get(key)
    if client is None:
        client = AsyncMongoClient(
            uri, tz_aware=True, tlsCAFile=certifi.where(), appname="biocurate"
        )
        _clients[key] = client
    return AtlasConn(client=client, db=client[cfg.storage.atlas_db], prefix=cfg.storage.atlas_prefix)


async def shutdown_clients() -> None:
    """Close every cached client."""
    clients = list(_clients.values())
    _clients.clear()
    for c in clients:
        await c.close()
