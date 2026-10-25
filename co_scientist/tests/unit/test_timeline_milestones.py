"""Agents post chat-timeline milestones; a failing post never fails the agent."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from co_scientist import ids
from co_scientist.agents import ranking as ranking_mod
from co_scientist.agents.base import AgentDeps
from co_scientist.agents.evolution import EvolutionAgent
from co_scientist.agents.generation import GenerationAgent
from co_scientist.agents.ranking import RankingAgent
from co_scientist.agents.reflection import ReflectionAgent
from co_scientist.agents.supervisor import Supervisor
from co_scientist.config import Config
from co_scientist.models import Hypothesis, ResearchPlan, Session
from co_scientist.storage.repos import events as events_repo
from co_scientist.storage.repos import hypotheses as hyp_repo
from co_scientist.storage.repos import sessions as sess_repo
from co_scientist.storage.repos import timeline as timeline_repo
from co_scientist.storage.repos import tournaments as tourney_repo


def _session() -> Session:
    return Session(
        id=ids.session_id(), created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
        status="running", research_goal="g", research_plan=ResearchPlan(objective="g"),
        config_snapshot={}, budget_tokens=1000, budget_usd=1.0,
    )


async def _msgs(conn, sid: str):
    return await timeline_repo.list_for_session(conn, sid)


async def _setup(tmp_cfg, conn):
    s = _session()
    await sess_repo.insert(conn, s)
    return s, AgentDeps(cfg=tmp_cfg, db=conn, llm=MagicMock(), tools=MagicMock())


_RECORD = {
    "title": "KEAP1 and cisplatin",
    "statement": "KEAP1 loss drives resistance. It acts through NRF2.",
    "mechanism": "m",
}


async def test_generation_posts_hypothesis_created(tmp_cfg, conn, monkeypatch) -> None:
    s, deps = await _setup(tmp_cfg, conn)
    monkeypatch.setattr(GenerationAgent, "_dedup_query", AsyncMock(return_value=(None, None)))
    hid, new = await GenerationAgent(deps)._persist(s.id, dict(_RECORD), strategy="literature")
    assert new
    [m] = await _msgs(conn, s.id)
    assert m.kind == "hypothesis_created"
    assert m.title == "KEAP1 and cisplatin"
    assert m.body_markdown == "KEAP1 loss drives resistance"
    assert list(m.refs) == [hid]
    assert m.agent == "generation"
    events = await events_repo.recent(conn, s.id)
    assert any(e["event"] == "hypothesis_generated" for e in events)
    ev = next(e for e in events if e["event"] == "hypothesis_generated")
    assert ev["payload"]["hypothesis_id"] == hid
    assert ev["payload"]["state"] == "draft"
    assert ev["payload"]["title"] == "KEAP1 and cisplatin"


async def test_milestone_post_failure_does_not_fail_agent(tmp_cfg, conn, monkeypatch) -> None:
    s, deps = await _setup(tmp_cfg, conn)
    monkeypatch.setattr(GenerationAgent, "_dedup_query", AsyncMock(return_value=(None, None)))

    async def boom(*a, **kw):
        raise RuntimeError("db down")

    monkeypatch.setattr(timeline_repo, "append", boom)
    hid, new = await GenerationAgent(deps)._persist(s.id, dict(_RECORD), strategy="literature")
    assert new
    assert await hyp_repo.fetch(conn, hid) is not None


async def test_evolution_posts_evolution_completed(tmp_cfg, conn, monkeypatch) -> None:
    s, deps = await _setup(tmp_cfg, conn)
    monkeypatch.setattr(EvolutionAgent, "_dedup_query", AsyncMock(return_value=(None, None)))
    hid, new = await EvolutionAgent(deps)._persist(s.id, dict(_RECORD), strategy="combine")
    assert new
    [m] = await _msgs(conn, s.id)
    assert (m.kind, m.title, m.agent) == (
        "evolution_completed", "Evolved: KEAP1 and cisplatin", "evolution"
    )
    assert list(m.refs) == [hid]
    events = await events_repo.recent(conn, s.id)
    assert any(e["event"] == "hypothesis_generated" for e in events)
    ev = next(e for e in events if e["event"] == "hypothesis_generated")
    assert ev["payload"]["hypothesis_id"] == hid
    assert ev["payload"]["state"] == "draft"


async def test_reflection_posts_review_completed(tmp_cfg, conn, monkeypatch) -> None:
    from co_scientist.agents import reflection as ref_mod

    s, deps = await _setup(tmp_cfg, conn)
    h = Hypothesis(
        id="hyp_r", session_id=s.id, created_at=datetime.now(UTC), created_by="generation",
        strategy="literature", title="t", summary="s", full_text="f", artifact_path="a",
    )
    assert await hyp_repo.insert(conn, h)
    record = {"verdict": "missing_piece", "novelty": 0.8, "correctness": 0.5, "evidence": []}
    resp = SimpleNamespace(response=object(), seen_urls=set())
    monkeypatch.setattr(ref_mod, "run_tool_loop", AsyncMock(return_value=resp))
    monkeypatch.setattr(ReflectionAgent, "_final_tool_use", lambda self, r, n: dict(record))
    deps.tools.anthropic_tools_for.return_value = []
    task = SimpleNamespace(id="tsk_1", session_id=s.id, payload={}, target_id="hyp_r")
    await ReflectionAgent(deps).execute(task)
    [m] = await _msgs(conn, s.id)
    assert m.kind == "review_completed"
    assert m.title == "Review: missing_piece"
    assert m.body_markdown == "novelty 0.80 · correctness 0.50"
    assert list(m.refs) == ["hyp_r"]
    events = await events_repo.recent(conn, s.id)
    assert any(e["event"] == "hypothesis_reviewed" for e in events)
    ev = next(e for e in events if e["event"] == "hypothesis_reviewed")
    assert ev["payload"]["hypothesis_id"] == "hyp_r"
    assert ev["payload"]["state"] == "reviewed"
    assert ev["payload"]["verdict"] == "missing_piece"


async def test_reflection_result_unchanged_when_post_fails(tmp_cfg, conn, monkeypatch) -> None:
    from co_scientist.agents import reflection as ref_mod

    s, deps = await _setup(tmp_cfg, conn)
    for hid in ("hyp_ok", "hyp_boom"):
        assert await hyp_repo.insert(conn, Hypothesis(
            id=hid, session_id=s.id, created_at=datetime.now(UTC), created_by="generation",
            strategy="literature", title="t", summary="s", full_text="f", artifact_path="a",
        ))
    record = {"verdict": "missing_piece", "novelty": 0.8, "evidence": []}
    resp = SimpleNamespace(response=object(), seen_urls=set())
    monkeypatch.setattr(ref_mod, "run_tool_loop", AsyncMock(return_value=resp))
    monkeypatch.setattr(ReflectionAgent, "_final_tool_use", lambda self, r, n: dict(record))
    deps.tools.anthropic_tools_for.return_value = []

    def task(hid: str):
        return SimpleNamespace(id="tsk_1", session_id=s.id, payload={}, target_id=hid)

    expected = await ReflectionAgent(deps).execute(task("hyp_ok"))

    async def boom(*a, **kw):
        raise RuntimeError("db down")

    monkeypatch.setattr(timeline_repo, "append", boom)
    got = await ReflectionAgent(deps).execute(task("hyp_boom"))

    assert got.kind == expected.kind == "review_completed"
    assert got.extra == expected.extra == {"verdict": "missing_piece"}
    assert len(got.review_ids) == len(expected.review_ids) == 1
    assert got.hypothesis_ids == ["hyp_boom"] and expected.hypothesis_ids == ["hyp_ok"]
    assert [m.refs for m in await _msgs(conn, s.id)] == [["hyp_ok"]]


def _h(hid: str) -> Hypothesis:
    return Hypothesis(
        id=hid, session_id="ses", created_at=datetime.now(UTC), created_by="generation",
        strategy="literature", title=f"title {hid}", summary="s", full_text="f",
        artifact_path="a", elo=1200.0, matches_played=0, state="in_tournament",
    )


async def test_match_result_sampling(monkeypatch: pytest.MonkeyPatch) -> None:
    a, b = _h("a"), _h("b")
    plan = SimpleNamespace(objective="o", preferences=["p"], idea_attributes=["i"])
    session = SimpleNamespace(id="ses", research_goal="g", research_plan=plan)
    count = {"n": 0}

    async def fetch(db, sid):
        return session

    async def list_for_session(db, sid, state=None):
        return [a, b]

    async def select_pair(self, sid, cands, focus_id=None):
        return a, b, 0.5

    async def run_debate(self, session, x, y, *, mode):
        return "a", "r", "tr", "end_turn"

    async def insert_match(db, m):
        return None

    async def record(db, **kw):
        count["n"] += 1
        return SimpleNamespace(
            elo_a_before=1200.0, elo_a_after=1216.0, elo_b_before=1200.0, elo_b_after=1184.0,
        )

    async def count_matches(db, sid):
        return count["n"]

    posted: list[tuple[int, dict]] = []

    async def post(conn, sid, **kw):
        posted.append((count["n"], kw))

    monkeypatch.setattr(ranking_mod.sess_repo, "fetch", fetch)
    monkeypatch.setattr(ranking_mod.hyp_repo, "list_for_session", list_for_session)
    monkeypatch.setattr(ranking_mod.tourney_repo, "insert_match", insert_match)
    monkeypatch.setattr(ranking_mod.tourney_repo, "record_match_result", record)
    monkeypatch.setattr(ranking_mod.tourney_repo, "count_matches", count_matches)
    monkeypatch.setattr(ranking_mod.timeline, "post", post)
    monkeypatch.setattr(RankingAgent, "_select_pair", select_pair)
    monkeypatch.setattr(RankingAgent, "_run_debate", run_debate)
    deps = SimpleNamespace(cfg=Config(), db=object(), llm=None)
    agent = RankingAgent(deps)
    for i in range(25):
        task = SimpleNamespace(
            id=f"tsk_{i}", session_id="ses", payload={}, target_id=None,
            action="RunTournamentBatch",
        )
        await agent._run_tournament_batch(task)
    assert [n for n, _ in posted] == [*range(1, 11), 20]
    kw = posted[0][1]
    assert kw["kind"] == "match_result"
    assert kw["title"] == "title a beat title b"
    assert kw["body"] == "Elo 1200 → 1216 / 1200 → 1184"


async def test_overview_ready_posted_by_simple_overview(tmp_cfg, conn) -> None:
    s, _ = await _setup(tmp_cfg, conn)
    await Supervisor(tmp_cfg)._write_simple_overview(conn, s)
    msgs = await _msgs(conn, s.id)
    assert [(m.kind, m.title) for m in msgs] == [("overview_ready", "Research overview ready")]


async def test_finalize_posts_session_done_once(tmp_cfg, conn, monkeypatch) -> None:
    from co_scientist.orchestrator.termination import StopReason

    s, deps = await _setup(tmp_cfg, conn)
    sup = Supervisor(tmp_cfg)
    await sup._finalize(conn, deps, s, StopReason.WALL_CLOCK)
    done = [m for m in await _msgs(conn, s.id) if m.kind == "session_done"]
    assert len(done) == 1
    assert done[0].title == "Session finished"
    assert done[0].body_markdown == StopReason.WALL_CLOCK.value


def test_count_matches_exists() -> None:
    assert callable(tourney_repo.count_matches)
