"""Backend-dispatching `attachments` repository."""

from __future__ import annotations

from ..atlas import attachments as _atlas
from ..sqlite import attachments as _sql
from ._dispatch import dual

insert = dual(_sql.insert, _atlas.insert)
list_for_session = dual(_sql.list_for_session, _atlas.list_for_session)
fetch = dual(_sql.fetch, _atlas.fetch)
set_status = dual(_sql.set_status, _atlas.set_status)
session_bytes = dual(_sql.session_bytes, _atlas.session_bytes)
total_bytes = dual(_sql.total_bytes, _atlas.total_bytes)
older_than = dual(_sql.older_than, _atlas.older_than)
delete = dual(_sql.delete, _atlas.delete)
