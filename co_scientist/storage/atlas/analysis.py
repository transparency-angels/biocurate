"""Atlas implementations for `analysis`."""

from __future__ import annotations

from typing import Any

from ._codec import aware, now
from .client import AtlasConn

_REPORTS = "analysis_reports"
_POINTS = "analysis_points"

REPORT_FIELDS = (
    "summary_markdown", "tests", "methods", "candidates", "selection",
    "sample_count", "drugs", "plots", "generated_at", "profile_type", "tables",
    "group_comparisons", "group_comparisons_total", "correlations", "join_audit", "screening",
)


async def save_report(conn: AtlasConn, session_id: str, report: dict[str, Any]) -> None:
    doc = {k: report[k] for k in REPORT_FIELDS if k in report}
    doc["created_at"] = now()
    await conn.coll(_REPORTS).replace_one({"_id": session_id}, doc, upsert=True)


async def fetch_report(conn: AtlasConn, session_id: str) -> dict[str, Any] | None:
    d = await conn.coll(_REPORTS).find_one({"_id": session_id})
    if d is None:
        return None
    d.pop("_id", None)
    d["created_at"] = aware(d["created_at"])
    return d


async def save_points(
    conn: AtlasConn, session_id: str, candidate_key: str, *,
    metric: str, unit: str, points: list[dict[str, Any]],
) -> None:
    await conn.coll(_POINTS).replace_one(
        {"session_id": session_id, "candidate_key": candidate_key},
        {
            "session_id": session_id, "candidate_key": candidate_key,
            "metric": metric, "unit": unit, "points": points,
        },
        upsert=True,
    )


async def fetch_points(
    conn: AtlasConn, session_id: str, candidate_keys: list[str]
) -> dict[str, dict[str, Any]]:
    if not candidate_keys:
        return {}
    cur = conn.coll(_POINTS).find(
        {"session_id": session_id, "candidate_key": {"$in": list(candidate_keys)}}
    )
    return {
        d["candidate_key"]: {"metric": d["metric"], "unit": d["unit"], "points": d["points"]}
        async for d in cur
    }
