"""Backend-dispatching `analysis` repository."""

from __future__ import annotations

from ..atlas import analysis as _atlas
from ..sqlite import analysis as _sql
from ._dispatch import dual

save_report = dual(_sql.save_report, _atlas.save_report)
fetch_report = dual(_sql.fetch_report, _atlas.fetch_report)
save_points = dual(_sql.save_points, _atlas.save_points)
fetch_points = dual(_sql.fetch_points, _atlas.fetch_points)
