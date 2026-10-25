"""Offline round-trip tests for the Atlas document mappers."""

from __future__ import annotations

from datetime import UTC, datetime

from co_scientist.models import (
    AssumptionCheck,
    CitedPaper,
    Evidence,
    Hypothesis,
    ResearchPlan,
    Review,
    ReviewScores,
    Session,
    SystemFeedback,
    Task,
    TournamentMatch,
    Transcript,
)
from co_scientist.storage.atlas import feedback as a_fb
from co_scientist.storage.atlas import hypotheses as a_hyp
from co_scientist.storage.atlas import reviews as a_rev
from co_scientist.storage.atlas import sessions as a_ses
from co_scientist.storage.atlas import tasks as a_tasks
from co_scientist.storage.atlas import tournaments as a_tm
from co_scientist.storage.atlas import transcripts as a_tx

T0 = datetime(2026, 10, 24, 12, 0, 0, 123000, tzinfo=UTC)


def test_hypothesis_doc_roundtrip() -> None:
    h = Hypothesis(
        id="hyp_1", session_id="s", created_at=T0, created_by="generation",
        strategy="literature", parent_ids=["a", "b"], title="t", summary="s",
        full_text="f", artifact_path="p", elo=None, state="draft",
        citations=[CitedPaper(title="P", url="u", year=2020, line_range="L3-L5")],
        data_evidence={"source": "tcga", "rows": [1, 2]},
    )
    doc = a_hyp._to_doc(h)
    assert doc["_id"] == "hyp_1" and "id" not in doc
    assert doc["citations"][0]["line_range"] == "L3-L5"
    assert doc["data_evidence"] == {"source": "tcga", "rows": [1, 2]}
    assert doc["parent_ids"] == ["a", "b"] and doc["elo"] is None
    assert a_hyp._from_doc(doc) == h


def test_hypothesis_from_doc_tolerates_missing_parent_ids_and_naive_dates() -> None:
    h = Hypothesis(
        id="hyp_2", session_id="s", created_at=T0, created_by="evolution",
        strategy="combine", title="t", summary="s", full_text="f", artifact_path="p",
        elo=1200.0, matches_played=3, state="pinned", dedup_cluster="c",
    )
    doc = a_hyp._to_doc(h)
    doc["parent_ids"] = None
    doc["created_at"] = T0.replace(tzinfo=None)  # client without tz_aware
    assert a_hyp._from_doc(doc) == h


def test_hypothesis_from_doc_defaults_citations_and_data_evidence() -> None:
    doc = {
        "_id": "hyp_legacy",
        "session_id": "ses_leg",
        "created_at": T0,
        "created_by": "generation",
        "strategy": "literature",
        "title": "Legacy Title",
        "summary": "Legacy summary",
        "full_text": "Legacy full text",
        "artifact_path": "artifacts/ses_leg/hypotheses/hyp_legacy.json",
        "matches_played": 0,
        "state": "draft",
    }
    h = a_hyp._from_doc(doc)
    assert h.citations == []
    assert h.data_evidence is None


def test_session_doc_roundtrip_nested_plan() -> None:
    s = Session(
        id="ses_1", created_at=T0, updated_at=T0, status="running", research_goal="g",
        research_plan=ResearchPlan(objective="x", preferences=["p"], domain_hint="bio"),
        config_snapshot={"k": {"n": [1, 2]}}, budget_tokens=10, budget_usd=1.5,
        wall_deadline=T0,
    )
    doc = a_ses._to_doc(s)
    assert doc["_id"] == "ses_1"
    assert doc["research_plan"]["preferences"] == ["p"]  # native subdocument
    assert doc["config_snapshot"] == {"k": {"n": [1, 2]}}
    assert a_ses._from_doc(doc) == s


def test_session_roundtrip_without_deadline() -> None:
    s = Session(
        id="ses_2", created_at=T0, updated_at=T0, status="done", research_goal="g",
        research_plan=ResearchPlan(objective="x"), config_snapshot={},
        budget_tokens=1, budget_usd=1.0, final_overview="a/b.md",
    )
    assert a_ses._from_doc(a_ses._to_doc(s)) == s


def test_session_row_matches_sqlite_column_order() -> None:
    s = Session(
        id="ses_3", created_at=T0, updated_at=T0, status="running", research_goal="g",
        research_plan=ResearchPlan(objective="x"), config_snapshot={"k": 1},
        budget_tokens=1, budget_usd=1.0,
    )
    row = a_ses._doc_to_row(a_ses._to_doc(s))
    assert list(row) == [
        "id", "created_at", "updated_at", "status", "research_goal", "research_plan",
        "config_snapshot", "budget_tokens", "budget_usd", "budget_used_tokens",
        "budget_used_usd", "wall_deadline", "final_overview",
    ]
    assert row["created_at"] == "2026-10-24T12:00:00.123000+00:00"
    assert row["wall_deadline"] is None
    assert row["research_plan"]["objective"] == "x"


def test_review_doc_roundtrip() -> None:
    r = Review(
        id="rev_1", hypothesis_id="h", session_id="s", created_at=T0, kind="full",
        verdict=None, scores=ReviewScores(novelty=0.5, feasibility=None),
        evidence=[Evidence(claim="c", url="u", excerpt="e", line_range="L1-L2")],
        assumptions=[AssumptionCheck(assumption="a", plausibility="plausible", rationale="r")],
        body="b", artifact_path="p",
    )
    doc = a_rev._to_doc(r)
    assert doc["_id"] == "rev_1"
    assert doc["evidence"][0]["line_range"] == "L1-L2"
    assert a_rev._from_doc(doc) == r


def test_feedback_doc_roundtrip() -> None:
    f = SystemFeedback(
        id="fb_1", session_id="s", created_at=T0, source="human", kind="pin",
        target_id=None, text="t", artifact_path=None, active=False,
    )
    doc = a_fb._to_doc(f)
    assert doc["_id"] == "fb_1" and doc["active"] is False and doc["target_id"] is None
    assert a_fb._from_doc(doc) == f


def test_transcript_doc_roundtrip() -> None:
    t = Transcript(
        id="tx_1", session_id="s", task_id=None, agent="a", action="x", model="m",
        input_tokens=1, output_tokens=2, cache_read=3, cache_write=4, cost_usd=0.5,
        started_at=T0, finished_at=T0, artifact_path="p",
    )
    doc = a_tx._to_doc(t)
    assert doc["_id"] == "tx_1"
    assert a_tx._from_doc(doc) == t


def test_task_doc_roundtrip() -> None:
    t = Task(
        id="tsk_1", session_id="s", created_at=T0, started_at=T0, finished_at=None,
        agent="reflection", action="ReviewHypothesis", target_id="h",
        payload={"a": {"b": [1]}}, priority=7, status="leased", lease_owner="w",
        lease_expires_at=1_700_000_000_000, attempts=2, last_error="e", idempotency_key="k",
    )
    doc = a_tasks._to_doc(t)
    assert doc["_id"] == "tsk_1" and "id" not in doc
    assert doc["payload"] == {"a": {"b": [1]}}  # native subdocument
    assert isinstance(doc["lease_expires_at"], int)
    assert a_tasks._from_doc(doc) == t


def test_task_doc_omits_null_idempotency_key_and_tolerates_naive_dates() -> None:
    t = Task(
        id="tsk_2", session_id="s", created_at=T0, agent="reflection",
        action="ReviewHypothesis",
    )
    doc = a_tasks._to_doc(t)
    # the unique partial index only covers string keys; null would still be indexed-safe,
    # but omitting keeps documents clean
    assert "idempotency_key" not in doc
    doc["created_at"] = T0.replace(tzinfo=None)
    assert a_tasks._from_doc(doc) == t


def test_tournament_match_doc_roundtrip() -> None:
    m = TournamentMatch(
        id="m1", session_id="s", created_at=T0, hyp_a="a", hyp_b="b", mode="debate",
        winner=None, elo_a_before=1200.0, elo_b_before=1210.5, elo_a_after=1216.0,
        elo_b_after=None, rationale="r", transcript_id="tx", similarity=0.25,
    )
    doc = a_tm._to_doc(m)
    assert doc["_id"] == "m1" and doc["winner"] is None and doc["elo_b_after"] is None
    assert a_tm._from_doc(doc) == m
