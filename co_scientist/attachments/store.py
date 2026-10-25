"""Persist accepted uploads (blob + metadata row) under the configured quotas."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from .. import ids
from ..config import Config
from ..models.attachment import AttachmentMeta
from ..storage import Conn
from ..storage.repos import attachments as att_repo
from ..storage.repos import blobs
from .intake import IncomingFile

_MB = 1024 * 1024


class AttachmentQuotaError(ValueError):
    """The upload would exceed the per-session or total attachment storage limit."""


async def check_quota(
    conn: Conn, cfg: Config, session_id: str | None, files: list[IncomingFile],
) -> None:
    """Raise AttachmentQuotaError if `files` do not fit; `session_id=None` means a new session."""
    new_bytes = sum(len(f.data) for f in files)
    limits = cfg.attachments
    used = await att_repo.session_bytes(conn, session_id) if session_id else 0
    if used + new_bytes > limits.max_session_mb * _MB:
        raise AttachmentQuotaError(
            f"attachments exceed the {limits.max_session_mb} MB per-session limit"
        )
    if await att_repo.total_bytes(conn) + new_bytes > limits.max_total_mb * _MB:
        raise AttachmentQuotaError(f"attachments exceed the {limits.max_total_mb} MB storage limit")


async def store_incoming(
    conn: Conn, cfg: Config, session_id: str, files: list[IncomingFile],
) -> list[AttachmentMeta]:
    """Store `files` for a session; raises AttachmentQuotaError first if a quota is exceeded."""
    if not files:
        return []
    await check_quota(conn, cfg, session_id, files)
    stored: list[AttachmentMeta] = []
    for f in files:
        blob_id = await blobs.put(
            conn, "attachments", f.filename, f.data, {"session_id": session_id},
        )
        meta = AttachmentMeta(
            id=ids.attachment_id(), session_id=session_id, filename=f.filename,
            content_type=f.content_type, size=len(f.data),
            sha256=hashlib.sha256(f.data).hexdigest(), kind=f.kind, status="stored",
            blob_id=blob_id, uploaded_at=datetime.now(UTC),
        )
        if await att_repo.insert(conn, meta):
            stored.append(meta)
        else:
            await blobs.delete(conn, "attachments", blob_id)
    return stored
