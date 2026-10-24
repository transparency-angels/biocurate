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
    embeddings as emb_repo,
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
    spans as span_repo,
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
    # Millisecond precision: BSON dates (Atlas) cannot hold microseconds.
    t = datetime.now(UTC)
    return t.replace(microsecond=t.microsecond // 1000 * 1000)


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
    assert list(one) == [
        "id", "status", "research_goal", "created_at", "updated_at",
        "budget_usd", "budget_used_usd", "n_hyps", "top_elo",
    ]
    assert one["created_at"] == s1.created_at.isoformat()
    assert one["updated_at"] == s1.updated_at.isoformat()


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


# --------------------------------------------------------------------------- #
# Functions not covered above, so the Atlas twins are exercised too


@pytest.mark.asyncio
async def test_session_status_usage_and_overview(any_conn) -> None:
    s = await _make_session(any_conn)
    await sess_repo.set_status(any_conn, s.id, "paused")
    got = await sess_repo.fetch(any_conn, s.id)
    assert got is not None and got.status == "paused" and got.updated_at >= s.updated_at

    await sess_repo.add_usage(any_conn, s.id, 100, 0.25)
    await sess_repo.add_usage(any_conn, s.id, 50, 0.5)
    got = await sess_repo.fetch(any_conn, s.id)
    assert got is not None
    assert got.budget_used_tokens == 150 and got.budget_used_usd == pytest.approx(0.75)

    await sess_repo.set_final_overview(any_conn, s.id, "artifacts/x/overview.md")
    got = await sess_repo.fetch(any_conn, s.id)
    assert got is not None
    assert got.status == "done" and got.final_overview == "artifacts/x/overview.md"
    # untouched fields survive the partial updates
    assert got.research_plan.objective == "x" and got.config_snapshot == {"k": 1}


@pytest.mark.asyncio
async def test_hypothesis_reads_and_simple_writes(any_conn) -> None:
    s = await _make_session(any_conn)
    await _seed_hyps(any_conn, s.id)  # elos: 1200, 1250, None
    h0, h1, h2 = (f"hyp_{s.id}_{i}" for i in range(3))

    many = await hyp_repo.fetch_many(any_conn, [h0, h2, "missing"])
    assert {h.id for h in many} == {h0, h2}
    assert await hyp_repo.fetch_many(any_conn, []) == []
    assert await hyp_repo.fetch(any_conn, "missing") is None

    # elo DESC, NULL last
    assert [h.id for h in await hyp_repo.list_for_session(any_conn, s.id)] == [h1, h0, h2]
    only = await hyp_repo.list_for_session(any_conn, s.id, state="pinned")
    assert [h.id for h in only] == [h1]

    # top_by_elo only considers in_tournament / pinned
    assert [h.id for h in await hyp_repo.top_by_elo(any_conn, s.id, k=10)] == [h1, h0]
    assert [h.id for h in await hyp_repo.top_by_elo(any_conn, s.id, k=1)] == [h1]

    await hyp_repo.set_state(any_conn, h2, "rejected")
    await hyp_repo.set_dedup_cluster(any_conn, h2, "clu")
    got = await hyp_repo.fetch(any_conn, h2)
    assert got is not None and got.state == "rejected" and got.dedup_cluster == "clu"
    await hyp_repo.set_dedup_cluster(any_conn, h2, None)
    got = await hyp_repo.fetch(any_conn, h2)
    assert got is not None and got.dedup_cluster is None


@pytest.mark.asyncio
async def test_hypothesis_roundtrip_keeps_parents_and_defaults(any_conn) -> None:
    s = await _make_session(any_conn)
    h = _hyp(s.id, 0)
    h = Hypothesis(**{**h.model_dump(), "parent_ids": ["p1", "p2"], "created_by": "evolution"})
    await hyp_repo.insert(any_conn, h)
    got = await hyp_repo.fetch(any_conn, h.id)
    assert got == h


@pytest.mark.asyncio
async def test_set_state_if_same_state_counts_as_applied(any_conn) -> None:
    s = await _make_session(any_conn)
    h = _hyp(s.id, 0, state="draft")
    await hyp_repo.insert(any_conn, h)
    assert await hyp_repo.set_state_if(
        any_conn, h.id, new_state="draft", expected_states=("draft",)
    ) is True
    assert await hyp_repo.set_state_if(
        any_conn, "missing", new_state="draft", expected_states=("draft",)
    ) is False


@pytest.mark.asyncio
async def test_review_reads(any_conn) -> None:
    from datetime import timedelta

    s = await _make_session(any_conn)
    h = _hyp(s.id, 0)
    await hyp_repo.insert(any_conn, h)
    t0 = _now()
    revs = []
    for i in range(3):
        r = Review(
            id=f"rev{i}", hypothesis_id=h.id, session_id=s.id,
            created_at=t0 + timedelta(seconds=i), kind="full", verdict=None,
            scores=ReviewScores(novelty=0.1 * i), body="b", artifact_path="p",
        )
        revs.append(r)
        assert await rev_repo.insert(any_conn, r) is True
    got = await rev_repo.fetch(any_conn, "rev1")
    assert got == revs[1]
    assert await rev_repo.fetch(any_conn, "nope") is None
    assert [r.id for r in await rev_repo.list_for_hypothesis(any_conn, h.id)] == [
        "rev2", "rev1", "rev0",
    ]
    assert [r.id for r in await rev_repo.list_for_session(any_conn, s.id)] == [
        "rev2", "rev1", "rev0",
    ]
    assert await rev_repo.list_for_hypothesis(any_conn, "other") == []


@pytest.mark.asyncio
async def test_feedback_latest_and_deactivate(any_conn) -> None:
    from datetime import timedelta

    s = await _make_session(any_conn)
    t0 = _now()
    for i, (src, kind) in enumerate(
        [("meta_review", "system_feedback"), ("human", "system_feedback"),
         ("meta_review", "system_feedback"), ("meta_review", "directive")]
    ):
        await fb_repo.insert(any_conn, SystemFeedback(
            id=f"fb{i}", session_id=s.id, created_at=t0 + timedelta(seconds=i),
            source=src, kind=kind, text=f"t{i}", artifact_path=None,
        ))
    latest = await fb_repo.latest_system_feedback(any_conn, s.id)
    assert latest is not None and latest.id == "fb2"
    assert await fb_repo.latest_system_feedback(any_conn, "empty") is None

    await fb_repo.deactivate(any_conn, "fb3")
    ids_ = [f.id for f in await fb_repo.active_for_session(any_conn, s.id)]
    assert ids_ == ["fb2", "fb1", "fb0"]  # created_at DESC, fb3 inactive
    got = await fb_repo.active_for_session(any_conn, s.id)
    assert got[0].active is True and got[0].target_id is None


@pytest.mark.asyncio
async def test_usage_summary(any_conn) -> None:
    from co_scientist.models import Transcript

    s = await _make_session(any_conn)
    empty = await tx_repo.usage_summary(any_conn, s.id)
    assert empty == {
        "input_tokens": 0, "output_tokens": 0, "cache_read": 0, "cache_write": 0,
        "cost_usd": 0.0, "n_calls": 0,
    }
    t0 = _now()
    for i in range(2):
        await tx_repo.insert(any_conn, Transcript(
            id=f"tx{i}", session_id=s.id, task_id=None, agent="a", action="x", model="m",
            input_tokens=10, output_tokens=5, cache_read=2, cache_write=1, cost_usd=0.5,
            started_at=t0, finished_at=t0, artifact_path="p",
        ))
    got = await tx_repo.usage_summary(any_conn, s.id)
    assert got == {
        "input_tokens": 20, "output_tokens": 10, "cache_read": 4, "cache_write": 2,
        "cost_usd": 1.0, "n_calls": 2,
    }
    assert await tx_repo.durations_ms(any_conn, s.id) == [0, 0]


@pytest.mark.asyncio
async def test_events_recent(any_conn) -> None:
    import asyncio

    s = await _make_session(any_conn)
    for i in range(3):
        await events_repo.emit(
            any_conn, session_id=s.id, task_id="t", agent="a", event=f"e{i}",
            payload={"i": i} if i != 1 else None,
        )
        await asyncio.sleep(0.01)
    await events_repo.emit(
        any_conn, session_id="other", task_id=None, agent=None, event="x", payload={},
    )
    rows = await events_repo.recent(any_conn, s.id)
    assert [r["event"] for r in rows] == ["e2", "e1", "e0"]
    assert rows[0]["payload"] == {"i": 2} and rows[1]["payload"] is None
    assert set(rows[0]) == {"ts", "session_id", "task_id", "agent", "event", "payload"}
    assert isinstance(rows[0]["ts"], int) and rows[0]["ts"] >= rows[2]["ts"]
    assert len(await events_repo.recent(any_conn, s.id, limit=2)) == 2
    other = await events_repo.recent(any_conn, "other")
    assert other[0]["payload"] is None and other[0]["task_id"] is None


async def _read_span(conn, span_id: str) -> dict:
    """Backend-specific read of one span: {attrs, status, started_at, ended_at}."""
    from co_scientist.storage.atlas.client import AtlasConn

    if isinstance(conn, AtlasConn):
        d = await conn.coll("spans").find_one({"_id": span_id})
        assert d is not None
        return {k: d[k] for k in ("attrs", "status", "started_at", "ended_at")}
    async with conn.execute(
        "SELECT attrs_json, status, started_at, ended_at FROM spans WHERE span_id=?",
        (span_id,),
    ) as cur:
        row = await cur.fetchone()
    assert row is not None
    return {
        "attrs": json.loads(row["attrs_json"]),
        "status": row["status"],
        "started_at": row["started_at"],
        "ended_at": row["ended_at"],
    }


@pytest.mark.asyncio
async def test_spans_start_and_end(any_conn) -> None:
    sid = await span_repo.start(
        any_conn, trace_id="tr", parent_span_id=None, session_id="s", task_id=None,
        name="n", attrs={"a": 1, "b": {"x": 1}},
    )
    assert isinstance(sid, str) and sid
    before = await _read_span(any_conn, sid)
    assert before["status"] == "unset" and before["ended_at"] is None
    assert before["attrs"] == {"a": 1, "b": {"x": 1}}

    await span_repo.end(any_conn, sid, status="ok", attrs={"a": 3, "c": 2})
    got = await _read_span(any_conn, sid)
    assert got["attrs"] == {"a": 3, "b": {"x": 1}, "c": 2}  # new wins, old kept
    assert got["status"] == "ok"
    assert got["ended_at"] is not None and got["ended_at"] >= got["started_at"]

    sid2 = await span_repo.start(
        any_conn, trace_id="tr", parent_span_id=sid, session_id="s", task_id=None,
        name="m", attrs={"k": "v"},
    )
    await span_repo.end(any_conn, sid2, status="error")
    got2 = await _read_span(any_conn, sid2)
    assert got2["attrs"] == {"k": "v"}
    assert got2["status"] == "error" and got2["ended_at"] is not None

    # `$`-prefixed string values are data, not expressions
    sid3 = await span_repo.start(
        any_conn, trace_id="tr", parent_span_id=None, session_id="s", task_id=None, name="d",
    )
    await span_repo.end(any_conn, sid3, attrs={"v": "$notafield"})
    assert (await _read_span(any_conn, sid3))["attrs"] == {"v": "$notafield"}

    await span_repo.end(any_conn, "missing")  # no-op, must not raise


@pytest.mark.asyncio
async def test_list_with_stats_limit_zero_returns_empty(any_conn) -> None:
    await _make_session(any_conn)
    assert await sess_repo.list_with_stats(any_conn, limit=0) == []


@pytest.mark.asyncio
async def test_embeddings_meta(any_conn) -> None:
    s = await _make_session(any_conn)
    h = _hyp(s.id, 0)
    await hyp_repo.insert(any_conn, h)
    h1 = _hyp(s.id, 1)
    await hyp_repo.insert(any_conn, h1)
    kw = {"session_id": s.id, "model": "m", "dim": 8}
    assert await emb_repo.has_embedding(any_conn, h.id, "m") is False
    assert await emb_repo.fetch_offset(any_conn, h.id, "m") is None
    await emb_repo.upsert(any_conn, id_="e1", hypothesis_id=h.id, faiss_offset=5,
                          text_hash="x", **kw)
    await emb_repo.upsert(any_conn, id_="e0", hypothesis_id=h1.id, faiss_offset=2,
                          text_hash="y", **kw)
    assert await emb_repo.has_embedding(any_conn, h.id, "m") is True
    assert await emb_repo.has_embedding(any_conn, h.id, "other") is False
    # re-upsert on the same (hypothesis, model): offset/hash replaced, id kept
    await emb_repo.upsert(any_conn, id_="e9", hypothesis_id=h.id, faiss_offset=7,
                          text_hash="z", **kw)
    assert await emb_repo.fetch_offset(any_conn, h.id, "m") == 7
    rows = await emb_repo.list_for_session(any_conn, s.id)
    assert rows == [
        {"id": "e0", "hypothesis_id": h1.id, "model": "m", "dim": 8,
         "faiss_offset": 2, "text_hash": "y"},
        {"id": "e1", "hypothesis_id": h.id, "model": "m", "dim": 8,
         "faiss_offset": 7, "text_hash": "z"},
    ]
    assert await emb_repo.list_for_session(any_conn, "empty") == []
