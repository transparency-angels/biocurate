"""Atlas implementations for `blobs` (GridFS)."""

from __future__ import annotations

import contextlib

from bson import ObjectId
from gridfs import AsyncGridFSBucket
from gridfs.errors import NoFile

from .client import AtlasConn


def _bucket(conn: AtlasConn, bucket: str) -> AsyncGridFSBucket:
    return AsyncGridFSBucket(conn.db, bucket_name=conn.prefix + bucket)


async def put(conn: AtlasConn, bucket: str, name: str, data: bytes, metadata: dict) -> str:
    """Store bytes in GridFS; returns `str(ObjectId)`."""
    oid = await _bucket(conn, bucket).upload_from_stream(name, data, metadata=metadata)
    return str(oid)


async def get(conn: AtlasConn, bucket: str, blob_id: str) -> bytes:
    try:
        stream = await _bucket(conn, bucket).open_download_stream(ObjectId(blob_id))
    except NoFile as e:
        raise KeyError(f"blob {blob_id!r} not found in bucket {bucket!r}") from e
    return await stream.read()


async def delete(conn: AtlasConn, bucket: str, blob_id: str) -> None:
    with contextlib.suppress(NoFile):
        await _bucket(conn, bucket).delete(ObjectId(blob_id))
