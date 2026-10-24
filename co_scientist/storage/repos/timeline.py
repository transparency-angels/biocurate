"""Backend-dispatching `timeline` repository."""

from __future__ import annotations

from ..atlas import timeline as _atlas
from ..sqlite import timeline as _sql
from ._dispatch import dual

append = dual(_sql.append, _atlas.append)
list_for_session = dual(_sql.list_for_session, _atlas.list_for_session)
