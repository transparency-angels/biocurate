"""Backend-dispatching `reviews` repository."""

from __future__ import annotations

from ..atlas import reviews as _atlas
from ..sqlite import reviews as _sql
from ._dispatch import dual

insert = dual(_sql.insert, _atlas.insert)
fetch = dual(_sql.fetch, _atlas.fetch)
list_for_hypothesis = dual(_sql.list_for_hypothesis, _atlas.list_for_hypothesis)
list_for_session = dual(_sql.list_for_session, _atlas.list_for_session)
