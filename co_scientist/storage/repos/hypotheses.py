"""Backend-dispatching `hypotheses` repository."""

from __future__ import annotations

from ..atlas import hypotheses as _atlas
from ..sqlite import hypotheses as _sql
from ._dispatch import dual

insert = dual(_sql.insert, _atlas.insert)
fetch = dual(_sql.fetch, _atlas.fetch)
fetch_many = dual(_sql.fetch_many, _atlas.fetch_many)
list_for_session = dual(_sql.list_for_session, _atlas.list_for_session)
top_by_elo = dual(_sql.top_by_elo, _atlas.top_by_elo)
count_by_state = dual(_sql.count_by_state, _atlas.count_by_state)
elo_range = dual(_sql.elo_range, _atlas.elo_range)
top_elo_ids = dual(_sql.top_elo_ids, _atlas.top_elo_ids)
pool_size = dual(_sql.pool_size, _atlas.pool_size)
set_state = dual(_sql.set_state, _atlas.set_state)
set_state_if = dual(_sql.set_state_if, _atlas.set_state_if)
init_tournament = dual(_sql.init_tournament, _atlas.init_tournament)
set_dedup_cluster = dual(_sql.set_dedup_cluster, _atlas.set_dedup_cluster)
