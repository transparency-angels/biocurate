"""Timeline message model: a short human-readable note posted as work happens."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

TimelineRole = Literal["system", "user", "assistant"]


@dataclass(frozen=True)
class TimelineMessage:
    session_id: str
    seq: int
    ts: datetime
    role: TimelineRole
    agent: str | None
    kind: str
    title: str
    body_markdown: str
    refs: list[str]
