"""Backend-dispatching `events` repository."""

from __future__ import annotations

from ..atlas import events as _atlas
from ..sqlite import events as _sql
from ._dispatch import dual

emit = dual(_sql.emit, _atlas.emit)
recent = dual(_sql.recent, _atlas.recent)
tool_call_counts = dual(_sql.tool_call_counts, _atlas.tool_call_counts)
