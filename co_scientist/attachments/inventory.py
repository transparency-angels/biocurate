"""A compact description of a session's attachments for the planning step."""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any

from ..config import Config
from ..storage import Conn
from ..storage.datasets import table_delimiter
from ..storage.repos import attachments as att_repo
from ..storage.repos import blobs

PEEK_BYTES = 64 * 1024
MAX_ROWS = 3
MAX_CELL = 100
MAX_COLUMNS = 200


def _peek(filename: str, data: bytes) -> tuple[list[str] | None, list[list[str]] | None]:
    text = data[:PEEK_BYTES].decode("utf-8", errors="replace").lstrip("﻿")
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=table_delimiter(Path(filename)))
    try:
        header = next(reader, None)
        if header is None:
            return None, None
        rows = []
        for row in reader:
            rows.append([c[:MAX_CELL] for c in row[:MAX_COLUMNS]])
            if len(rows) == MAX_ROWS:
                break
    except csv.Error:
        return None, None
    return [c[:MAX_CELL] for c in header[:MAX_COLUMNS]], rows


async def build_inventory(conn: Conn, cfg: Config, session_id: str) -> list[dict[str, Any]]:
    """One entry per attachment; tabular files also get a header and up to 3 sample rows."""
    out: list[dict[str, Any]] = []
    for a in await att_repo.list_for_session(conn, session_id):
        header = rows = None
        if a.kind == "tabular":
            data = await blobs.get(conn, "attachments", a.blob_id)
            header, rows = _peek(a.filename, data)
        out.append({
            "id": a.id, "filename": a.filename, "kind": a.kind, "size": a.size,
            "header": header, "sample_rows": rows,
        })
    return out
