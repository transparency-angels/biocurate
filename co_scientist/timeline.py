"""Best-effort timeline poster: persist a message, then fan it out on the bus."""

from __future__ import annotations

from typing import Any

from .logging import get_logger
from .models.timeline import TimelineMessage
from .orchestrator.events import GLOBAL_BUS
from .storage.repos import timeline as timeline_repo

log = get_logger(__name__)


def to_payload(m: TimelineMessage) -> dict[str, Any]:
    """The wire shape shared by the bus event and the `/timeline` endpoint."""
    return {
        "seq": m.seq,
        "ts": int(m.ts.timestamp() * 1000),
        "role": m.role,
        "agent": m.agent,
        "kind": m.kind,
        "title": m.title,
        "body_markdown": m.body_markdown,
        "refs": list(m.refs),
    }


async def post(
    conn: Any,
    session_id: str,
    *,
    kind: str,
    title: str,
    body: str = "",
    agent: str | None = None,
    refs: list[str] | None = None,
) -> None:
    """Append a timeline message and publish it. Never raises."""
    try:
        msg = await timeline_repo.append(
            conn,
            session_id,
            role="system",
            agent=agent,
            kind=kind,
            title=title,
            body_markdown=body,
            refs=list(refs or []),
        )
        await GLOBAL_BUS.publish(session_id, "timeline_message", to_payload(msg))
    except Exception as e:
        log.warning(
            "timeline_post_failed", session_id=session_id, kind=kind, err_type=type(e).__name__
        )
