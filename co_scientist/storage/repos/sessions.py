"""Backend-dispatching `sessions` repository."""

from __future__ import annotations

from ..atlas import sessions as _atlas
from ..sqlite import sessions as _sql
from ._dispatch import dual

insert = dual(_sql.insert, _atlas.insert)
fetch = dual(_sql.fetch, _atlas.fetch)
fetch_row = dual(_sql.fetch_row, _atlas.fetch_row)
set_status = dual(_sql.set_status, _atlas.set_status)
add_usage = dual(_sql.add_usage, _atlas.add_usage)
set_final_overview = dual(_sql.set_final_overview, _atlas.set_final_overview)
list_with_stats = dual(_sql.list_with_stats, _atlas.list_with_stats)
ids_created_since = dual(_sql.ids_created_since, _atlas.ids_created_since)
ids_for_goal = dual(_sql.ids_for_goal, _atlas.ids_for_goal)
set_research_plan = dual(_sql.set_research_plan, _atlas.set_research_plan)
delete = dual(_sql.delete, _atlas.delete)
