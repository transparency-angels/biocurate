"""Read-only metrics aggregations for the web UI dashboards.

All counts roll up from existing tables (transcripts, tournament_matches, etc.)
— no separate metrics store. Keep queries small and indexed.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from ..storage import Conn
from ..storage.repos import events as events_repo
from ..storage.repos import hypotheses as hyp_repo
from ..storage.repos import tasks as task_repo
from ..storage.repos import tournaments as tourney_repo
from ..storage.repos import transcripts as tx_repo


@dataclass
class SessionMetrics:
    n_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read: int = 0
    cache_write: int = 0
    cost_usd: float = 0.0
    cache_hit_ratio: float | None = None
    n_matches: int = 0
    n_invalid_matches: int = 0
    n_hypotheses: int = 0
    n_in_tournament: int = 0
    n_reviewed: int = 0
    p50_latency_ms: float | None = None
    p95_latency_ms: float | None = None
    tools_called: int = 0
    tool_errors: int = 0
    dead_tasks: int = 0


async def session_metrics(conn: Conn, session_id: str) -> SessionMetrics:
    out = SessionMetrics()

    # LLM usage (from transcripts)
    usage = await tx_repo.usage_summary(conn, session_id)
    if usage:
        out.n_calls = usage["n_calls"]
        out.input_tokens = usage["input_tokens"]
        out.output_tokens = usage["output_tokens"]
        out.cache_read = usage["cache_read"]
        out.cache_write = usage["cache_write"]
        out.cost_usd = float(usage["cost_usd"])
        denom = out.cache_read + out.cache_write + out.input_tokens
        if denom > 0:
            out.cache_hit_ratio = out.cache_read / denom

    # Matches
    by_mode = await tourney_repo.count_by_mode(conn, session_id)
    out.n_invalid_matches = by_mode.get("invalid", 0)
    out.n_matches = sum(n for mode, n in by_mode.items() if mode != "invalid")

    # Hypotheses
    states = await hyp_repo.count_by_state(conn, session_id)
    out.n_hypotheses = sum(states.values())
    out.n_in_tournament = sum(states.get(s, 0) for s in ("in_tournament", "pinned"))
    out.n_reviewed = sum(states.get(s, 0) for s in ("reviewed", "in_tournament", "pinned"))

    # Latency P50/P95 from transcripts (whole-second resolution).
    durations = await tx_repo.durations_ms(conn, session_id)
    if durations:
        out.p50_latency_ms = _percentile(durations, 0.50)
        out.p95_latency_ms = _percentile(durations, 0.95)

    # Tool calls + errors (from events)
    out.tools_called, out.tool_errors = await events_repo.tool_call_counts(conn, session_id)

    # Dead-lettered tasks
    out.dead_tasks = (await task_repo.count_by_status(conn, session_id)).get("dead", 0)

    return out


def _percentile(sorted_values: list[float], p: float) -> float:
    if not sorted_values:
        return 0.0
    i = max(0, min(len(sorted_values) - 1, round(p * (len(sorted_values) - 1))))
    return float(sorted_values[i])


@dataclass
class LeaderboardEntry:
    hypothesis_id: str
    title: str
    elo: float | None
    matches_played: int


async def leaderboard(
    conn: Conn, session_id: str, k: int = 10
) -> list[LeaderboardEntry]:
    hyps = await hyp_repo.top_by_elo(conn, session_id, k)
    return [
        LeaderboardEntry(
            hypothesis_id=h.id, title=h.title, elo=h.elo, matches_played=h.matches_played,
        )
        for h in hyps
    ]


# Tiny in-memory cache to dampen UI hot-polling.
_CACHE: dict[str, tuple[float, SessionMetrics]] = {}


async def session_metrics_cached(
    conn: Conn, session_id: str, *, ttl_s: float = 1.0
) -> SessionMetrics:
    now = time.monotonic()
    hit = _CACHE.get(session_id)
    if hit is not None and now - hit[0] < ttl_s:
        return hit[1]
    m = await session_metrics(conn, session_id)
    _CACHE[session_id] = (now, m)
    return m


def to_dict(m: SessionMetrics) -> dict[str, Any]:
    return {
        "n_calls": m.n_calls,
        "input_tokens": m.input_tokens,
        "output_tokens": m.output_tokens,
        "cache_read": m.cache_read,
        "cache_write": m.cache_write,
        "cost_usd": m.cost_usd,
        "cache_hit_ratio": m.cache_hit_ratio,
        "n_matches": m.n_matches,
        "n_invalid_matches": m.n_invalid_matches,
        "n_hypotheses": m.n_hypotheses,
        "n_in_tournament": m.n_in_tournament,
        "n_reviewed": m.n_reviewed,
        "p50_latency_ms": m.p50_latency_ms,
        "p95_latency_ms": m.p95_latency_ms,
        "tools_called": m.tools_called,
        "tool_errors": m.tool_errors,
        "dead_tasks": m.dead_tasks,
    }
