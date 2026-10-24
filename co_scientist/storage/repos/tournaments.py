"""Backend-dispatching `tournaments` repository."""

from __future__ import annotations

from ..atlas import tournaments as _atlas
from ..sqlite import tournaments as _sql
from ._dispatch import dual

insert_match = dual(_sql.insert_match, _atlas.insert_match)
apply_elo_update = dual(_sql.apply_elo_update, _atlas.apply_elo_update)
count_matches = dual(_sql.count_matches, _atlas.count_matches)
recent_rationales = dual(_sql.recent_rationales, _atlas.recent_rationales)
list_for_session = dual(_sql.list_for_session, _atlas.list_for_session)
list_for_hypothesis = dual(_sql.list_for_hypothesis, _atlas.list_for_hypothesis)
count_by_mode = dual(_sql.count_by_mode, _atlas.count_by_mode)
