"""Backend-dispatching `blobs` repository."""

from __future__ import annotations

from ..atlas import blobs as _atlas
from ..sqlite import blobs as _sql
from ._dispatch import dual

put = dual(_sql.put, _atlas.put)
get = dual(_sql.get, _atlas.get)
delete = dual(_sql.delete, _atlas.delete)
