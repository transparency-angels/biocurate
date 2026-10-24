"""Roundtrip tests for the storage repositories."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from co_scientist import ids
from co_scientist.models import (
    Hypothesis,
    ResearchPlan,
    Review,
    ReviewScores,
    Session,
    SystemFeedback,
    Task,
    TournamentMatch,
)
from co_scientist.storage.repos import (
    events as events_repo,
)
from co_scientist.storage.repos import (
    feedback as fb_repo,
)
from co_scientist.storage.repos import (
    hypotheses as hyp_repo,
)
from co_scientist.storage.repos import (
    reviews as rev_repo,
)
from co_scientist.storage.repos import (
    sessions as sess_repo,
)
from co_scientist.storage.repos import (
    tasks as task_repo,
)
from co_scientist.storage.repos import (
    tournaments as tourney_repo,
)
from co_scientist.storage.repos import (
    transcripts as tx_repo,
)


def _now() -> datetime:
    return datetime.now(UTC)


async def _make_session(conn, sid: str = "ses_test") -> Session:
    s = Session(
        id=sid, created_at=_now(), updated_at=_now(), status="running",
        research_goal="Test goal",
        research_plan=ResearchPlan(objective="x", preferences=["specificity"]),
        config_snapshot={"k": 1}, budget_tokens=10000, budget_usd=1.0,
    )
    await sess_repo.insert(conn, s)
    return s


@pytest.mark.asyncio
async def test_sessions_roundtrip(any_conn) -> None:
    s = await _make_session(any_conn)
    s2 = await sess_repo.fetch(any_conn, s.id)
    assert s2 is not None
    assert s2.research_goal == s.research_goal
    assert s2.research_plan.objective == "x"
    assert s2.research_plan.preferences == ["specificity"]
    assert s2.config_snapshot == {"k": 1}


@pytest.mark.asyncio
async def test_hypothesis_insert_or_ignore_dedupes_on_deterministic_id(any_conn) -> None:
    s = await _make_session(any_conn)
    statement = "Hypothesis: X causes Y via Z."
    hid = ids.hypothesis_id(s.id, "generation/literature", statement)
    h = Hypothesis(
        id=hid, session_id=s.id, created_at=_now(),
        created_by="generation", strategy="literature",
        title="t", summary=statement, full_text="long",
        artifact_path=f"artifacts/{s.id}/hypotheses/{hid}.json",
        state="draft",
    )
    assert await hyp_repo.insert(any_conn, h) is True
    # Same statement → same id → INSERT OR IGNORE returns False
    h2 = Hypothesis(**{**h.model_dump(), "title": "different title"})
    assert await hyp_repo.insert(any_conn, h2) is False
    fetched = await hyp_repo.fetch(any_conn, hid)
    assert fetched is not None
    assert fetched.title == "t"  # original wins


@pytest.mark.asyncio
async def test_init_tournament_only_runs_once(any_conn) -> None:
    s = await _make_session(any_conn)
    hid = ids.hypothesis_id(s.id, "generation/literature", "h")
    await hyp_repo.insert(any_conn, Hypothesis(
        id=hid, session_id=s.id, created_at=_now(),
        created_by="generation", strategy="literature",
        title="t", summary="s", full_text="f",
        artifact_path=f"artifacts/{s.id}/hypotheses/{hid}.json", state="reviewed",
    ))
    assert await hyp_repo.init_tournament(any_conn, hid, initial_elo=1200) is True
    # second call must be a no-op (Elo already set)
    assert await hyp_repo.init_tournament(any_conn, hid, initial_elo=9999) is False
    h = await hyp_repo.fetch(any_conn, hid)
    assert h is not None and h.elo == 1200


@pytest.mark.asyncio
async def test_set_state_if_only_applies_when_expected(any_conn) -> None:
    """set_state_if must only transition from one of the expected source states."""
    s = await _make_session(any_conn)
    hid = ids.hypothesis_id(s.id, "generation/literature", "h-state")
    await hyp_repo.insert(any_conn, Hypothesis(
        id=hid, session_id=s.id, created_at=_now(),
        created_by="generation", strategy="literature",
        title="t", summary="s", full_text="f",
        artifact_path=f"artifacts/{s.id}/hypotheses/{hid}.json", state="draft",
    ))
    # draft → reviewed: allowed
    applied = await hyp_repo.set_state_if(
        any_conn, hid, new_state="reviewed", expected_states=("draft",)
    )
    assert applied is True

    # Promote past reflection into the tournament.
    await hyp_repo.init_tournament(any_conn, hid, initial_elo=1200)

    # Reflection re-fires: must NOT drag in_tournament → reviewed.
    applied2 = await hyp_repo.set_state_if(
        any_conn, hid, new_state="reviewed", expected_states=("draft",)
    )
    assert applied2 is False
    h = await hyp_repo.fetch(any_conn, hid)
    assert h is not None and h.state == "in_tournament"


@pytest.mark.asyncio
async def test_review_id_iteration_collision_blocked(any_conn) -> None:
    s = await _make_session(any_conn)
    hid = ids.hypothesis_id(s.id, "generation/literature", "h")
    await hyp_repo.insert(any_conn, Hypothesis(
        id=hid, session_id=s.id, created_at=_now(),
        created_by="generation", strategy="literature",
        title="t", summary="s", full_text="f",
        artifact_path=f"artifacts/{s.id}/hypotheses/{hid}.json", state="draft",
    ))
    rid = ids.review_id(hid, "full", iteration=0)
    r = Review(
        id=rid, hypothesis_id=hid, session_id=s.id, created_at=_now(),
        kind="full", verdict="missing_piece",
        scores=ReviewScores(novelty=0.7, correctness=0.6, testability=0.5),
        body="ok", artifact_path=f"artifacts/{s.id}/reviews/{rid}.json",
    )
    assert await rev_repo.insert(any_conn, r) is True
    assert await rev_repo.insert(any_conn, r) is False   # idempotent


@pytest.mark.asyncio
async def test_task_queue_claim_and_idempotency(any_conn) -> None:
    s = await _make_session(any_conn)
    t = Task(
        id=ids.task_id(), session_id=s.id, created_at=_now(),
        agent="reflection", action="ReviewHypothesis", target_id="hyp_z",
        payload={}, priority=100, status="pending",
        idempotency_key="hyp_z::review::full",
    )
    assert await task_repo.enqueue(any_conn, t) is True
    assert await task_repo.enqueue(any_conn, t) is False   # idempotency_key collision

    claimed = await task_repo.claim_one(any_conn, s.id, "w1", lease_seconds=60)
    assert claimed is not None
    assert claimed.id == t.id
    assert claimed.status == "leased"

    # nothing else to claim
    again = await task_repo.claim_one(any_conn, s.id, "w1", lease_seconds=60)
    assert again is None


@pytest.mark.asyncio
async def test_feedback_targeting(any_conn) -> None:
    s = await _make_session(any_conn)
    await fb_repo.insert(any_conn, SystemFeedback(
        id=ids.feedback_id(), session_id=s.id, created_at=_now(),
        source="human", kind="directive", target_id=None,
        text="focus on insulin signaling", active=True,
    ))
    await fb_repo.insert(any_conn, SystemFeedback(
        id=ids.feedback_id(), session_id=s.id, created_at=_now(),
        source="human", kind="pin", target_id="hyp_keep_me",
        text="pinned", active=True,
    ))
    global_only = await fb_repo.active_for_session(any_conn, s.id)
    assert len(global_only) == 1
    assert global_only[0].kind == "directive"

    targeted = await fb_repo.active_for_session(any_conn, s.id, target_id="hyp_keep_me")
    assert {f.kind for f in targeted} == {"directive", "pin"}


# --------------------------------------------------------------------------- #
# Read helpers that used to be raw SQL in cli / web / mcp / agents / obs


def _hyp(session_id: str, n: int, *, state: str = "in_tournament", elo: float | None = None):
    return Hypothesis(
        id=f"hyp_{session_id}_{n}", session_id=session_id, created_at=_now(),
        created_by="generation", strategy="literature",
        title=f"t{n}", summary=f"s{n}", full_text="long",
        artifact_path=f"artifacts/{session_id}/hypotheses/{n}.json",
        state=state, elo=elo,
    )


async def _seed_hyps(any_conn, session_id: str) -> None:
    for n, (state, elo) in enumerate(
        [("in_tournament", 1200.0), ("pinned", 1250.0), ("reviewed", None)]
    ):
        await hyp_repo.insert(any_conn, _hyp(session_id, n, state=state, elo=elo))


def _match(session_id: str, n: int, hyp_a: str, hyp_b: str, mode: str = "debate"):
    from datetime import timedelta

    return TournamentMatch(
        id=f"m{n}", session_id=session_id, created_at=_now() + timedelta(seconds=n),
        hyp_a=hyp_a, hyp_b=hyp_b, mode=mode, winner="a",
        elo_a_before=1200.0, elo_b_before=1200.0,
    )


@pytest.mark.asyncio
async def test_list_with_stats_counts_hypotheses(any_conn) -> None:
    from datetime import timedelta

    s1 = await _make_session(any_conn, "ses_one")
    s2 = Session(
        id="ses_two", created_at=_now(), updated_at=_now() + timedelta(seconds=5),
        status="running", research_goal="g2", research_plan=ResearchPlan(objective="x"),
        config_snapshot={}, budget_tokens=1, budget_usd=1.0,
    )
    await sess_repo.insert(any_conn, s2)
    await _seed_hyps(any_conn, s1.id)
    rows = await sess_repo.list_with_stats(any_conn)
    assert [r["id"] for r in rows] == ["ses_two", "ses_one"]
    one = rows[1]
    assert one["n_hyps"] == 3
    assert one["top_elo"] == 1250
    assert rows[0]["n_hyps"] == 0 and rows[0]["top_elo"] is None
    assert {"status", "research_goal", "created_at", "updated_at"} <= set(one)
    assert len(await sess_repo.list_with_stats(any_conn, limit=1)) == 1


@pytest.mark.asyncio
async def test_session_id_lookups(any_conn) -> None:
    s = await _make_session(any_conn, "ses_a")
    await _make_session(any_conn, "ses_b")
    since = await sess_repo.ids_created_since(any_conn, "2000-01-01T00:00:00")
    assert set(since) == {"ses_a", "ses_b"}
    assert await sess_repo.ids_created_since(any_conn, "2999-01-01T00:00:00") == []
    assert set(await sess_repo.ids_for_goal(any_conn, s.research_goal)) == {"ses_a", "ses_b"}
    assert await sess_repo.ids_for_goal(any_conn, "nope") == []


@pytest.mark.asyncio
async def test_set_research_plan(any_conn) -> None:
    s = await _make_session(any_conn)
    await sess_repo.set_research_plan(any_conn, s.id, ResearchPlan(objective="new").model_dump())
    got = await sess_repo.fetch(any_conn, s.id)
    assert got is not None
    assert got.research_plan.objective == "new"
    assert got.updated_at >= s.updated_at


@pytest.mark.asyncio
async def test_count_by_state(any_conn) -> None:
    s = await _make_session(any_conn)
    await _seed_hyps(any_conn, s.id)
    assert await hyp_repo.count_by_state(any_conn, s.id) == {
        "in_tournament": 1, "pinned": 1, "reviewed": 1,
    }


@pytest.mark.asyncio
async def test_elo_range_ignores_null(any_conn) -> None:
    s = await _make_session(any_conn)
    await _seed_hyps(any_conn, s.id)
    assert await hyp_repo.elo_range(any_conn, s.id) == (1200.0, 1250.0, 2)
    assert await hyp_repo.elo_range(any_conn, "empty") == (None, None, 0)


@pytest.mark.asyncio
async def test_top_elo_ids_and_pool_size(any_conn) -> None:
    s = await _make_session(any_conn)
    await _seed_hyps(any_conn, s.id)
    await hyp_repo.insert(any_conn, _hyp(s.id, 9, state="rejected", elo=1500.0))
    assert await hyp_repo.top_elo_ids(any_conn, s.id, 5) == [
        (f"hyp_{s.id}_1", 1250.0), (f"hyp_{s.id}_0", 1200.0),
    ]
    assert len(await hyp_repo.top_elo_ids(any_conn, s.id, 1)) == 1
    assert await hyp_repo.pool_size(any_conn, s.id) == 2


@pytest.mark.asyncio
async def test_tournament_listings(any_conn) -> None:
    s = await _make_session(any_conn)
    await _seed_hyps(any_conn, s.id)
    a, b, c = (f"hyp_{s.id}_{i}" for i in range(3))
    for m in (_match(s.id, 1, a, b), _match(s.id, 2, b, c, "pairwise"), _match(s.id, 3, a, c)):
        await tourney_repo.insert_match(any_conn, m)
    recent = await tourney_repo.list_for_session(any_conn, s.id, limit=2)
    assert [m.id for m in recent] == ["m3", "m2"]
    for_a = await tourney_repo.list_for_hypothesis(any_conn, a)
    assert [m.id for m in for_a] == ["m1", "m3"]
    assert await tourney_repo.count_by_mode(any_conn, s.id) == {"debate": 2, "pairwise": 1}


@pytest.mark.asyncio
async def test_durations_ms_ascending(any_conn) -> None:
    from datetime import timedelta

    from co_scientist.models import Transcript

    s = await _make_session(any_conn)
    t0 = _now()
    for i, secs in enumerate([5, 2, 9]):
        await tx_repo.insert(any_conn, Transcript(
            id=f"tx{i}", session_id=s.id, task_id=None, agent="a", action="x", model="m",
            input_tokens=1, output_tokens=1, cache_read=0, cache_write=0, cost_usd=0.0,
            started_at=t0, finished_at=t0 + timedelta(seconds=secs), artifact_path="p",
        ))
    assert await tx_repo.durations_ms(any_conn, s.id) == [2000, 5000, 9000]


@pytest.mark.asyncio
async def test_count_meta_review(any_conn) -> None:
    s = await _make_session(any_conn)

    async def add(i: int, source: str, kind: str) -> None:
        await fb_repo.insert(any_conn, SystemFeedback(
            id=f"fb{i}", session_id=s.id, created_at=_now(), source=source,
            kind=kind, text="t", artifact_path="p",
        ))

    await add(1, "meta_review", "system_feedback")
    await add(2, "meta_review", "system_feedback")
    await add(3, "human", "system_feedback")
    assert await fb_repo.count_meta_review(any_conn, s.id) == 2


@pytest.mark.asyncio
async def test_tool_call_counts(any_conn) -> None:
    s = await _make_session(any_conn)
    for payload in ({"is_error": True}, {"is_error": False}, None):
        await events_repo.emit(
            any_conn, session_id=s.id, task_id=None, agent="a", event="tool_call", payload=payload,
        )
    await events_repo.emit(
        any_conn, session_id=s.id, task_id=None, agent="a", event="other",
        payload={"is_error": True},
    )
    assert await events_repo.tool_call_counts(any_conn, s.id) == (3, 1)


@pytest.mark.asyncio
async def test_fetch_row_keeps_stored_strings(any_conn) -> None:
    s = await _make_session(any_conn)
    row = await sess_repo.fetch_row(any_conn, s.id)
    assert row is not None
    assert row["created_at"] == s.created_at.isoformat()
    assert row["created_at"].endswith("+00:00")
    assert row["updated_at"].endswith("+00:00")
    assert row["wall_deadline"] is None
    assert row["research_plan"] == json.loads(s.research_plan.model_dump_json())
    assert row["config_snapshot"] == {"k": 1}
    assert list(row)[:3] == ["id", "created_at", "updated_at"]
    assert await sess_repo.fetch_row(any_conn, "missing") is None


@pytest.mark.asyncio
async def test_fetch_row_passes_malformed_json_through(conn) -> None:
    s = await _make_session(conn)
    await conn.execute("UPDATE sessions SET config_snapshot='{oops' WHERE id=?", (s.id,))
    await conn.commit()
    row = await sess_repo.fetch_row(conn, s.id)
    assert row is not None and row["config_snapshot"] == "{oops"
