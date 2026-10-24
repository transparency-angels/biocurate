"""Backend-dispatching `embeddings` repository."""

from __future__ import annotations

from ..atlas import embeddings as _atlas
from ..sqlite import embeddings as _sql
from ._dispatch import dual

upsert = dual(_sql.upsert, _atlas.upsert)
has_embedding = dual(_sql.has_embedding, _atlas.has_embedding)
list_for_session = dual(_sql.list_for_session, _atlas.list_for_session)
fetch_offset = dual(_sql.fetch_offset, _atlas.fetch_offset)
