"""Storage layer: SQLite (default) or MongoDB Atlas."""

from __future__ import annotations

from typing import Union

import aiosqlite

from .atlas.client import AtlasConn

# What `db.connect` returns: an aiosqlite connection or an Atlas handle.
# Spelled with a string forward reference so the alias is never evaluated with
# `|` at import time; scripts that stub third-party modules (e.g.
# scripts/verify_metareview_citations.py) can still import the package.
Conn = Union["aiosqlite.Connection", AtlasConn]

__all__ = ["AtlasConn", "Conn"]
