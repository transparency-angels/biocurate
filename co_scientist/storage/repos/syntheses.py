"""Backend-dispatching `syntheses` repository."""

from __future__ import annotations

from ..atlas import syntheses as _atlas
from ..sqlite import syntheses as _sql
from ._dispatch import dual

save = dual(_sql.save, _atlas.save)
fetch = dual(_sql.fetch, _atlas.fetch)
