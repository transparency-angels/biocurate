"""Load a session's final overview markdown, wherever it is stored."""

from __future__ import annotations

import json
from typing import Any

from .storage.repos import syntheses as syntheses_repo

DB_PREFIX = "db:syntheses/"


async def load_overview_markdown(conn: Any, cfg: Any, session: Any) -> str | None:
    """Return the overview markdown, or None when it is unavailable.

    `db:syntheses/<id>` paths read the database; anything else is a legacy file
    under `cfg.data_dir` (markdown, or cite-lines JSON with an `overview.markdown`).
    """
    ref = session.final_overview
    if not ref:
        return None
    if ref.startswith(DB_PREFIX):
        doc = await syntheses_repo.fetch(conn, ref[len(DB_PREFIX):])
        if doc is None:
            return None
        return (doc.get("overview") or {}).get("markdown")
    path = cfg.data_dir / ref
    if not path.is_file():
        return None
    content = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        try:
            data = json.loads(content)
            return data.get("overview", {}).get("markdown") or data.get("markdown") or content
        except Exception:
            return content
    return content
