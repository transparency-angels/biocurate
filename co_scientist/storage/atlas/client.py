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
from pymongo.errors import CollectionInvalid, OperationFailure

if TYPE_CHECKING:
    from ...config import Config

# uri -> (loop the client was created on, client). Keyed by URI alone and
# validated against the running loop: `id(loop)` is reused by CPython once a
# loop is collected, so an id-keyed cache can hand back a client bound to a
# dead loop.
_clients: dict[str, tuple[asyncio.AbstractEventLoop, AsyncMongoClient]] = {}


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
            except CollectionInvalid:  # lost a race: pymongo's "already exists"
                pass
            except OperationFailure as e:
                if e.code != 48:  # NamespaceExists
                    raise

    async def close(self) -> None:
        """No-op: the client is shared. See `shutdown_clients`."""

    def __repr__(self) -> str:
        return f"AtlasConn(db={self.db.name!r}, prefix={self.prefix!r})"


async def connect_atlas(cfg: Config) -> AtlasConn:
    uri = cfg.secrets.MONGODB_URI
    if not uri:
        raise RuntimeError("MONGODB_URI not set")
    loop = asyncio.get_running_loop()
    entry = _clients.get(uri)
    if entry is not None and (entry[0] is not loop or entry[0].is_closed()):
        # Bound to another (likely dead) loop; it cannot be closed from here.
        del _clients[uri]
        entry = None
    if entry is None:
        client = AsyncMongoClient(
            uri, tz_aware=True, tlsCAFile=certifi.where(), appname="biocurate"
        )
        _clients[uri] = (loop, client)
    else:
        client = entry[1]
    return AtlasConn(
        client=client,
        db=client[cfg.storage.atlas_db],
        prefix=cfg.storage.atlas_prefix,
    )


async def shutdown_clients() -> None:
    """Close every cached client."""
    clients = [c for lp, c in _clients.values() if lp is asyncio.get_running_loop()]
    _clients.clear()
    for c in clients:
        await c.close()
