"""Blob store (SQLite BLOB table; GridFS on Atlas)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import aiosqlite

from ... import ids


async def put(
    conn: aiosqlite.Connection, bucket: str, name: str, data: bytes, metadata: dict
) -> str:
    """Store bytes; returns the new blob id."""
    blob_id = ids.blob_id()
    await conn.execute(
        "INSERT INTO blobs(id, bucket, name, data, metadata, created_at) VALUES (?,?,?,?,?,?)",
        (blob_id, bucket, name, data, json.dumps(metadata), datetime.now(UTC).isoformat()),
    )
    await conn.commit()
    return blob_id


async def get(conn: aiosqlite.Connection, bucket: str, blob_id: str) -> bytes:
    async with conn.execute(
        "SELECT data FROM blobs WHERE id=? AND bucket=?", (blob_id, bucket)
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        raise KeyError(f"blob {blob_id!r} not found in bucket {bucket!r}")
    return bytes(row[0])


async def delete(conn: aiosqlite.Connection, bucket: str, blob_id: str) -> None:
    await conn.execute("DELETE FROM blobs WHERE id=? AND bucket=?", (blob_id, bucket))
    await conn.commit()
