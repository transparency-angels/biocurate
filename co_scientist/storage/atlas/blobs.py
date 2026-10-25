"""Atlas implementations for `blobs` (GridFS)."""

from __future__ import annotations

import contextlib

from bson import ObjectId
from bson.errors import InvalidId
from gridfs import AsyncGridFSBucket
from gridfs.errors import NoFile

from .client import AtlasConn


def _bucket(conn: AtlasConn, bucket: str) -> AsyncGridFSBucket:
    return AsyncGridFSBucket(conn.db, bucket_name=conn.prefix + bucket)


async def put(conn: AtlasConn, bucket: str, name: str, data: bytes, metadata: dict) -> str:
    """Store bytes in GridFS; returns `str(ObjectId)`."""
    oid = await _bucket(conn, bucket).upload_from_stream(name, data, metadata=metadata)
    return str(oid)


def _oid(blob_id: str) -> ObjectId | None:
    """Parse a blob id; a malformed one is treated as missing, as on SQLite."""
    try:
        return ObjectId(blob_id)
    except (InvalidId, TypeError):
        return None


async def get(conn: AtlasConn, bucket: str, blob_id: str) -> bytes:
    oid = _oid(blob_id)
    if oid is None:
        raise KeyError(f"blob {blob_id!r} not found in bucket {bucket!r}")
    try:
        stream = await _bucket(conn, bucket).open_download_stream(oid)
    except NoFile as e:
        raise KeyError(f"blob {blob_id!r} not found in bucket {bucket!r}") from e
    return await stream.read()


async def delete(conn: AtlasConn, bucket: str, blob_id: str) -> None:
    oid = _oid(blob_id)
    if oid is None:
        return
    with contextlib.suppress(NoFile):
        await _bucket(conn, bucket).delete(oid)
