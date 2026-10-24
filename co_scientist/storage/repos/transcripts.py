"""Backend-dispatching `transcripts` repository."""

from __future__ import annotations

from ..atlas import transcripts as _atlas
from ..sqlite import transcripts as _sql
from ._dispatch import dual

insert = dual(_sql.insert, _atlas.insert)
usage_summary = dual(_sql.usage_summary, _atlas.usage_summary)
durations_ms = dual(_sql.durations_ms, _atlas.durations_ms)
