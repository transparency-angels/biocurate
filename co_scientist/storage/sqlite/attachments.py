"""Attachment metadata repository."""

from __future__ import annotations

from datetime import datetime

import aiosqlite

from ...models.attachment import AttachmentMeta
from ..atlas._codec import aware


def _from_row(r) -> AttachmentMeta:
    return AttachmentMeta(
        id=r["id"],
        session_id=r["session_id"],
        filename=r["filename"],
        content_type=r["content_type"],
        size=r["size"],
        sha256=r["sha256"],
        kind=r["kind"],
        status=r["status"],
        blob_id=r["blob_id"],
        uploaded_at=aware(datetime.fromisoformat(r["uploaded_at"])),
        error=r["error"],
    )


async def insert(conn: aiosqlite.Connection, meta: AttachmentMeta) -> bool:
    """Insert; False if `(session_id, sha256, filename)` already exists."""
    cur = await conn.execute(
        """INSERT OR IGNORE INTO attachments(
               id, session_id, filename, content_type, size, sha256, kind,
               status, blob_id, uploaded_at, error)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            meta.id, meta.session_id, meta.filename, meta.content_type, meta.size,
            meta.sha256, meta.kind, meta.status, meta.blob_id,
            aware(meta.uploaded_at).isoformat(), meta.error,
        ),
    )
    inserted = cur.rowcount > 0
    await conn.commit()
    return inserted


async def list_for_session(conn: aiosqlite.Connection, session_id: str) -> list[AttachmentMeta]:
    async with conn.execute(
        "SELECT * FROM attachments WHERE session_id=? ORDER BY uploaded_at, id", (session_id,)
    ) as cur:
        return [_from_row(r) for r in await cur.fetchall()]


async def fetch(conn: aiosqlite.Connection, attachment_id: str) -> AttachmentMeta | None:
    async with conn.execute("SELECT * FROM attachments WHERE id=?", (attachment_id,)) as cur:
        row = await cur.fetchone()
    return _from_row(row) if row else None


async def set_status(
    conn: aiosqlite.Connection, attachment_id: str, status: str, error: str | None = None
) -> None:
    await conn.execute(
        "UPDATE attachments SET status=?, error=? WHERE id=?", (status, error, attachment_id)
    )
    await conn.commit()


async def session_bytes(conn: aiosqlite.Connection, session_id: str) -> int:
    async with conn.execute(
        "SELECT COALESCE(SUM(size), 0) FROM attachments WHERE session_id=?", (session_id,)
    ) as cur:
        row = await cur.fetchone()
    return int(row[0])


async def total_bytes(conn: aiosqlite.Connection) -> int:
    async with conn.execute("SELECT COALESCE(SUM(size), 0) FROM attachments") as cur:
        row = await cur.fetchone()
    return int(row[0])


async def older_than(conn: aiosqlite.Connection, cutoff: datetime) -> list[AttachmentMeta]:
    async with conn.execute(
        "SELECT * FROM attachments WHERE uploaded_at < ? ORDER BY uploaded_at, id",
        (aware(cutoff).isoformat(),),
    ) as cur:
        return [_from_row(r) for r in await cur.fetchall()]


async def delete(conn: aiosqlite.Connection, attachment_id: str) -> None:
    """Remove the metadata row only; callers delete the blob."""
    await conn.execute("DELETE FROM attachments WHERE id=?", (attachment_id,))
    await conn.commit()
