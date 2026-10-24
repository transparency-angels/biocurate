"""Backend dispatch for the repository modules."""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable
from typing import Any

from ..atlas.client import AtlasConn


def dual(
    sql_fn: Callable[..., Awaitable[Any]], atlas_fn: Callable[..., Awaitable[Any]]
) -> Callable[..., Awaitable[Any]]:
    """Route a repo call to the Atlas or SQLite implementation by connection type."""

    @functools.wraps(sql_fn)
    async def wrapper(conn, *args, **kwargs):
        fn = atlas_fn if isinstance(conn, AtlasConn) else sql_fn
        return await fn(conn, *args, **kwargs)

    return wrapper
