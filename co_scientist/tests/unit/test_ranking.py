"""Tests for the ranking verdict parser and mode-selection logic."""

from __future__ import annotations

from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import asyncio

import pytest
from structlog.testing import capture_logs

from co_scientist.agents import ranking as ranking_mod
from co_scientist.agents.ranking import RankingAgent, _parse_better_idea
from co_scientist.config import Config
from co_scientist.models import Hypothesis

# ----------------------------- verdict parser ----------------------------- #

def test_parse_better_idea_basic() -> None:
    assert _parse_better_idea("blah\nbetter idea: 1") == 1
    assert _parse_better_idea("blah\nbetter idea: 2") == 2


def test_parse_better_idea_trailing_marker_wins() -> None:
    text = "An earlier mention: better idea: 1\n\nFinal verdict.\nbetter idea: 2"
    assert _parse_better_idea(text) == 2


def test_parse_better_idea_handles_case_and_punctuation() -> None:
    assert _parse_better_idea("...\nBetter Idea: 2.") == 2
    assert _parse_better_idea("...\n**better idea**: 1") == 1


def test_parse_better_idea_returns_none_when_missing() -> None:
    assert _parse_better_idea("no verdict here") is None
    assert _parse_better_idea("") is None


def test_parse_better_idea_handles_qualifier_words() -> None:
    """Regression: the prior 'in tail.split()[0:1]' check rejected these."""
    assert _parse_better_idea("better idea: option 1") == 1
    assert _parse_better_idea("better idea: hypothesis 2") == 2
    assert _parse_better_idea("better idea: hyp 1") == 1


def test_parse_better_idea_word_boundary_excludes_12() -> None:
    """'better idea: 12 because...' must NOT be read as '1'."""
    # `12` should not match `[12]\b`.
    assert _parse_better_idea("better idea: 12 because of context") is None


# ----------------------------- mode selection ----------------------------- #

def _h(*, elo: float, matches: int, hid: str = "hyp_x") -> Hypothesis:
    return Hypothesis(
        id=hid, session_id="ses", created_at=datetime.now(UTC),
        created_by="generation", strategy="literature",
        title="t", summary="s", full_text="f",
        artifact_path=f"artifacts/ses/hypotheses/{hid}.json",
        elo=elo, matches_played=matches, state="in_tournament",
    )


def _agent() -> RankingAgent:
    deps = MagicMock()
    deps.cfg = Config()
    return RankingAgent(deps)


def test_mode_debate_when_either_player_has_few_matches() -> None:
    a = _h(hid="a", elo=1500, matches=0)
    b = _h(hid="b", elo=1500, matches=10)
    assert _agent()._select_mode(a, b) == "debate"


def test_mode_debate_when_elo_gap_is_small() -> None:
    a = _h(hid="a", elo=1500, matches=5)
    b = _h(hid="b", elo=1520, matches=5)
    assert _agent()._select_mode(a, b) == "debate"


def test_mode_pairwise_when_warm_and_large_gap() -> None:
    a = _h(hid="a", elo=1500, matches=10)
    b = _h(hid="b", elo=1300, matches=10)
    assert _agent()._select_mode(a, b) == "pairwise"


# ----------------------------- nearest-Elo helper ----------------------------- #

def test_nearest_elo_picks_closest() -> None:
    target = _h(hid="t", elo=1300, matches=0)
    pool = [
        _h(hid="a", elo=1000, matches=5),
        _h(hid="b", elo=1310, matches=5),    # closest
        _h(hid="c", elo=1500, matches=5),
    ]
    nearest = _agent()._nearest_elo(target, pool)
    assert nearest is not None and nearest.id == "b"


def test_nearest_elo_empty_pool() -> None:
    target = _h(hid="t", elo=1300, matches=0)
    assert _agent()._nearest_elo(target, []) is None


# ------------------------- output cap / invalid verdict ------------------------- #

def test_ranking_cfg_default_max_output_tokens() -> None:
    from co_scientist.config import load_config

    assert Config().ranking.max_output_tokens == 8192
    assert load_config().ranking.max_output_tokens == 8192
    assert "max_output_tokens = 8192" in Path("config/default.toml").read_text()


def _fake_llm(text: str, stop_reason: str, seen: list):
    class _LLM:
        async def call(self, spec, ctx):
            seen.append(spec)
            raw = SimpleNamespace(
                content=[SimpleNamespace(type="text", text=text)], stop_reason=stop_reason,
            )
            return SimpleNamespace(raw=raw, transcript_id="tr_1")

    return _LLM()


def _run_one_match(monkeypatch: pytest.MonkeyPatch, cfg: Config, llm) -> object:
    plan = SimpleNamespace(objective="o", preferences=["p"], idea_attributes=["i"])
    session = SimpleNamespace(id="ses", research_goal="g", research_plan=plan)
    a, b = _h(hid="a", elo=1200, matches=0), _h(hid="b", elo=1200, matches=0)

    async def fetch(db, sid):
        return session

    async def list_for_session(db, sid, state=None):
        return [a, b]

    async def select_pair(self, sid, cands, focus_id=None):
        return a, b, 0.5

    async def best_review(self, hid):
        return None

    async def insert_match(db, m):
        return None

    monkeypatch.setattr(ranking_mod.sess_repo, "fetch", fetch)
    monkeypatch.setattr(ranking_mod.hyp_repo, "list_for_session", list_for_session)
    monkeypatch.setattr(ranking_mod.tourney_repo, "insert_match", insert_match)
    monkeypatch.setattr(RankingAgent, "_select_pair", select_pair)
    monkeypatch.setattr(RankingAgent, "_best_review", best_review)
    deps = SimpleNamespace(cfg=cfg, db=object(), llm=llm)
    task = SimpleNamespace(
        id="tsk_1", session_id="ses", payload={}, target_id=None, action="RunTournamentBatch",
    )
    return RankingAgent(deps)._run_tournament_batch(task)


async def test_ranking_uses_configured_max_output_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = Config()
    cfg.ranking.max_output_tokens = 1234
    seen: list = []
    llm = _fake_llm("hm\nbetter idea: 1", "end_turn", seen)
    # Elo update follows a valid verdict; stop once the call has been made.
    with suppress(Exception):
        await _run_one_match(monkeypatch, cfg, llm)
    assert seen and seen[0].max_output_tokens == 1234


async def test_ranking_invalid_verdict_logs_stop_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list = []
    llm = _fake_llm("cut off mid-sentence", "max_tokens", seen)
    with capture_logs() as logs:
        result = await _run_one_match(monkeypatch, Config(), llm)
    assert result.extra == {"reason": "unparseable verdict"}
    warn = [e for e in logs if e["event"] == "ranking_invalid_verdict"]
    assert warn and warn[0]["stop_reason"] == "max_tokens"


async def test_ranking_uses_in_transaction_elo(monkeypatch: pytest.MonkeyPatch) -> None:
    from co_scientist.orchestrator.elo import AppliedElo

    calls: list[dict] = []
    applied = AppliedElo(
        elo_a_before=1300.0, elo_b_before=1100.0,
        elo_a_after=1310.0, elo_b_after=1090.0, k=16, expected_a=0.76,
    )

    async def record(db, **kw):
        calls.append(kw)
        return applied

    monkeypatch.setattr(ranking_mod.tourney_repo, "record_match_result", record)
    llm = _fake_llm("hm\nbetter idea: 1", "end_turn", [])
    with capture_logs() as logs:
        result = await _run_one_match(monkeypatch, Config(), llm)
    (kw,) = calls
    assert (kw["hyp_a"], kw["hyp_b"], kw["winner"]) == ("a", "b", "a")
    assert (kw["k_new"], kw["k_warm"], kw["initial_elo"]) == (32, 16, 1200)
    assert result.extra["elo_applied"] is True
    (done,) = [e for e in logs if e["event"] == "match_complete"]
    # the log reports the in-transaction values, not the pre-debate 1200s
    assert (done["elo_a"], done["elo_b"]) == (1310.0, 1090.0)
    assert done["applied"] is True


async def test_ranking_emits_match_completed_event(monkeypatch: pytest.MonkeyPatch) -> None:
    import contextlib
    from co_scientist.orchestrator.events import GLOBAL_BUS
    from co_scientist.orchestrator.elo import AppliedElo

    applied = AppliedElo(
        elo_a_before=1300.0, elo_b_before=1100.0,
        elo_a_after=1310.0, elo_b_after=1090.0, k=16, expected_a=0.76,
    )
    monkeypatch.setattr(
        ranking_mod.tourney_repo, "record_match_result", AsyncMock(return_value=applied)
    )
    llm = _fake_llm("The first hypothesis is clearer.\nbetter idea: 1", "end_turn", [])

    events_received: list[dict] = []

    async def sub() -> None:
        async with contextlib.aclosing(GLOBAL_BUS.subscribe("ses")) as stream:
            async for ev in stream:
                if ev.name == "match_completed":
                    events_received.append(ev.payload)
                    break

    sub_task = asyncio.create_task(sub())
    await asyncio.sleep(0.01)
    await _run_one_match(monkeypatch, Config(), llm)
    await asyncio.wait_for(sub_task, timeout=2.0)

    assert len(events_received) == 1
    ev = events_received[0]
    assert ev["winner"] == "a"
    assert ev["winner_id"] == "a"
    assert ev["loser_id"] == "b"
    assert ev["elo_a_after"] == 1310.0
    assert ev["elo_b_after"] == 1090.0
    assert "clearer" in ev["rationale_snippet"]
