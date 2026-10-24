"""Backend-dispatching `feedback` repository."""

from __future__ import annotations

from ..atlas import feedback as _atlas
from ..sqlite import feedback as _sql
from ._dispatch import dual

insert = dual(_sql.insert, _atlas.insert)
active_for_session = dual(_sql.active_for_session, _atlas.active_for_session)
latest_system_feedback = dual(_sql.latest_system_feedback, _atlas.latest_system_feedback)
deactivate = dual(_sql.deactivate, _atlas.deactivate)
count_meta_review = dual(_sql.count_meta_review, _atlas.count_meta_review)
