"""Storage layer: SQLite (default) or MongoDB Atlas."""

from __future__ import annotations

import aiosqlite

from .atlas.client import AtlasConn

# What `db.connect` returns: an aiosqlite connection or an Atlas handle.
Conn = aiosqlite.Connection | AtlasConn

__all__ = ["AtlasConn", "Conn"]
