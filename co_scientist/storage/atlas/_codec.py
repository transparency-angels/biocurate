"""Small helpers shared by the Atlas repos."""

from __future__ import annotations

from datetime import UTC, datetime


def aware(dt: datetime) -> datetime:
    """UTC-aware datetime (BSON dates carry no zone; naive means UTC)."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def iso(dt: datetime | None) -> str | None:
    """`.isoformat()` of a stored date, or None, as SQLite stores timestamps."""
    return None if dt is None else aware(dt).isoformat()


def now() -> datetime:
    return datetime.now(UTC)
