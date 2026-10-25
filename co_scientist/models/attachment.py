"""Attachment metadata model (file bytes live in the blob store)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

AttachmentKind = Literal["tabular", "document"]
AttachmentStatus = Literal["stored", "ingested", "analysed", "failed"]


@dataclass(frozen=True)
class AttachmentMeta:
    id: str
    session_id: str
    filename: str
    content_type: str
    size: int
    sha256: str
    kind: AttachmentKind
    status: AttachmentStatus
    blob_id: str
    uploaded_at: datetime
    error: str | None = None
