"""Backend-dispatching `tasks` repository."""

from __future__ import annotations

from ..atlas import tasks as _atlas
from ..sqlite import tasks as _sql
from ._dispatch import dual

enqueue = dual(_sql.enqueue, _atlas.enqueue)
claim_one = dual(_sql.claim_one, _atlas.claim_one)
heartbeat = dual(_sql.heartbeat, _atlas.heartbeat)
mark_in_progress = dual(_sql.mark_in_progress, _atlas.mark_in_progress)
complete = dual(_sql.complete, _atlas.complete)
fail = dual(_sql.fail, _atlas.fail)
cancel_pending_for_session = dual(
    _sql.cancel_pending_for_session, _atlas.cancel_pending_for_session
)
reclaim_expired_leases = dual(_sql.reclaim_expired_leases, _atlas.reclaim_expired_leases)
count_by_status = dual(_sql.count_by_status, _atlas.count_by_status)
