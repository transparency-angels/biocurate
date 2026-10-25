"""Atlas implementations for `sessions`."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ...models import ResearchPlan, Session
from ._codec import aware, iso, now
from .client import AtlasConn

_COLL = "sessions"


def _to_doc(s: Session) -> dict[str, Any]:
    return {
        "_id": s.id,
        "created_at": s.created_at,
        "updated_at": s.updated_at,
        "status": s.status,
        "research_goal": s.research_goal,
        "research_plan": s.research_plan.model_dump(mode="json"),
        "config_snapshot": s.config_snapshot,
        "budget_tokens": s.budget_tokens,
        "budget_usd": s.budget_usd,
        "budget_used_tokens": s.budget_used_tokens,
        "budget_used_usd": s.budget_used_usd,
        "wall_deadline": s.wall_deadline,
        "final_overview": s.final_overview,
    }


def _from_doc(d: dict[str, Any]) -> Session:
    deadline = d.get("wall_deadline")
    return Session(
        id=d["_id"],
        created_at=aware(d["created_at"]),
        updated_at=aware(d["updated_at"]),
        status=d["status"],
        research_goal=d["research_goal"],
        research_plan=ResearchPlan.model_validate(d["research_plan"]),
        config_snapshot=d["config_snapshot"],
        budget_tokens=d["budget_tokens"],
        budget_usd=d["budget_usd"],
        budget_used_tokens=d["budget_used_tokens"],
        budget_used_usd=d["budget_used_usd"],
        wall_deadline=aware(deadline) if deadline else None,
        final_overview=d.get("final_overview"),
    )


def _doc_to_row(d: dict[str, Any]) -> dict[str, Any]:
    """The SQLite `dict(row)` shape: same keys and order, ISO timestamps."""
    return {
        "id": d["_id"],
        "created_at": iso(d["created_at"]),
        "updated_at": iso(d["updated_at"]),
        "status": d["status"],
        "research_goal": d["research_goal"],
        "research_plan": d["research_plan"],
        "config_snapshot": d["config_snapshot"],
        "budget_tokens": d["budget_tokens"],
        "budget_usd": d["budget_usd"],
        "budget_used_tokens": d["budget_used_tokens"],
        "budget_used_usd": d["budget_used_usd"],
        "wall_deadline": iso(d.get("wall_deadline")),
        "final_overview": d.get("final_overview"),
    }


async def insert(conn: AtlasConn, s: Session) -> None:
    await conn.coll(_COLL).insert_one(_to_doc(s))


async def fetch(conn: AtlasConn, session_id: str) -> Session | None:
    d = await conn.coll(_COLL).find_one({"_id": session_id})
    return _from_doc(d) if d else None


async def fetch_row(conn: AtlasConn, session_id: str) -> dict | None:
    """Raw session row as a plain dict (timestamps as ISO strings)."""
    d = await conn.coll(_COLL).find_one({"_id": session_id})
    return _doc_to_row(d) if d else None


async def set_status(conn: AtlasConn, session_id: str, status: str) -> None:
    await conn.coll(_COLL).update_one(
        {"_id": session_id}, {"$set": {"status": status, "updated_at": now()}}
    )


async def add_usage(conn: AtlasConn, session_id: str, tokens: int, usd: float) -> None:
    await conn.coll(_COLL).update_one(
        {"_id": session_id},
        {
            "$inc": {"budget_used_tokens": tokens, "budget_used_usd": usd},
            "$set": {"updated_at": now()},
        },
    )


async def set_final_overview(conn: AtlasConn, session_id: str, rel_path: str) -> None:
    await conn.coll(_COLL).update_one(
        {"_id": session_id},
        {"$set": {"final_overview": rel_path, "status": "done", "updated_at": now()}},
    )


async def list_with_stats(conn: AtlasConn, *, limit: int | None = None) -> list[dict]:
    """Sessions newest-updated first, with hypothesis count and best Elo."""
    if limit is not None and limit <= 0:  # Mongo `$limit` must be positive
        return []
    pipeline: list[dict[str, Any]] = [{"$sort": {"updated_at": -1, "_id": -1}}]
    if limit is not None:
        pipeline.append({"$limit": limit})
    pipeline.append(
        {
            "$lookup": {
                "from": conn.coll("hypotheses").name,
                "localField": "_id",
                "foreignField": "session_id",
                "pipeline": [
                    {"$group": {"_id": None, "n": {"$sum": 1}, "top": {"$max": "$elo"}}}
                ],
                "as": "_st",
            }
        }
    )
    out = []
    cur = await conn.coll(_COLL).aggregate(pipeline)
    async for d in cur:
        st = d["_st"][0] if d["_st"] else {}
        out.append(
            {
                "id": d["_id"],
                "status": d["status"],
                "research_goal": d["research_goal"],
                "created_at": iso(d["created_at"]),
                "updated_at": iso(d["updated_at"]),
                "budget_usd": d["budget_usd"],
                "budget_used_usd": d["budget_used_usd"],
                "n_hyps": st.get("n", 0),
                "top_elo": st.get("top"),
            }
        )
    return out


def _parse_ts(iso_ts: str) -> datetime:
    return aware(datetime.fromisoformat(iso_ts))


async def ids_created_since(conn: AtlasConn, iso_ts: str) -> list[str]:
    cur = conn.coll(_COLL).find({"created_at": {"$gte": _parse_ts(iso_ts)}}, {"_id": 1})
    return [d["_id"] async for d in cur]


async def ids_for_goal(conn: AtlasConn, goal: str) -> list[str]:
    """Session ids with exactly this research goal, newest first."""
    cur = (
        conn.coll(_COLL)
        .find({"research_goal": goal}, {"_id": 1})
        .sort([("created_at", -1), ("_id", -1)])
    )
    return [d["_id"] async for d in cur]


async def set_research_plan(conn: AtlasConn, session_id: str, plan: dict) -> None:
    await conn.coll(_COLL).update_one(
        {"_id": session_id}, {"$set": {"research_plan": plan, "updated_at": now()}}
    )


async def delete(conn: AtlasConn, session_id: str) -> bool:
    """Delete one terminal session and its session-scoped Atlas documents."""
    session = await conn.coll(_COLL).find_one({"_id": session_id}, {"status": 1})
    if session is None:
        return False
    if session.get("status") in {"running", "paused"}:
        raise ValueError("Stop this research before deleting it.")

    matches = conn.coll("tournament_matches")
    match_ids = [row["_id"] async for row in matches.find({"session_id": session_id}, {"_id": 1})]
    if match_ids:
        await conn.coll("elo_journal").delete_many({"match_id": {"$in": match_ids}})

    attachment_rows = conn.coll("attachments_meta").find({"session_id": session_id}, {"blob_id": 1})
    from .blobs import delete as delete_blob
    async for attachment in attachment_rows:
        if attachment.get("blob_id"):
            await delete_blob(conn, "attachments", attachment["blob_id"])

    for collection in (
        "tournament_matches", "transcripts", "tasks", "system_feedback", "reviews",
        "embeddings_meta", "spans", "events", "timeline", "attachments_meta",
        "analysis_reports", "analysis_points", "syntheses", "hypothesis_vectors", "hypotheses",
    ):
        await conn.coll(collection).delete_many({"session_id": session_id})
    result = await conn.coll(_COLL).delete_one({"_id": session_id})
    return result.deleted_count > 0
