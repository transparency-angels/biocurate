"""Backend-dispatching `timeline` repository."""

from __future__ import annotations

from ..atlas import timeline as _atlas
from ..sqlite import timeline as _sql
from ._dispatch import dual

# `seq` is unique and strictly increasing per session. On Atlas it may have gaps
# (an insert that fails after the counter increment skips a number); on SQLite it
# is gap-free. Readers must use `seq > last`, never assume contiguity.

append = dual(_sql.append, _atlas.append)
list_for_session = dual(_sql.list_for_session, _atlas.list_for_session)
