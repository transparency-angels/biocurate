"""Tests for the pure Elo math + idempotent persistence."""

from __future__ import annotations

import math
from datetime import UTC, datetime

import pytest

from co_scientist import ids
from co_scientist.models import Hypothesis, TournamentMatch
from co_scientist.orchestrator.elo import expected_score, k_factor, update_elo
from co_scientist.storage.repos import hypotheses as hyp_repo
from co_scientist.storage.repos import tournaments as tourney_repo


def test_equal_ratings_expect_half() -> None:
    assert expected_score(1200, 1200) == pytest.approx(0.5)


def test_higher_rating_favored() -> None:
    assert expected_score(1500, 1200) > 0.8
    assert expected_score(1200, 1500) < 0.2


def test_k_factor_decays() -> None:
    assert k_factor(0) == 32
    assert k_factor(4) == 32
    assert k_factor(5) == 16
    assert k_factor(100) == 16


def test_update_zero_sum() -> None:
    u = update_elo(1200, 1200, "a", matches_played_min=0)
    # zero-sum
    assert math.isclose(u.elo_a_after + u.elo_b_after, 2400, abs_tol=1e-9)
    # winner gains, loser drops
    assert u.elo_a_after > 1200
    assert u.elo_b_after < 1200


def test_underdog_win_is_high_payoff() -> None:
    u = update_elo(1100, 1500, "a", matches_played_min=10)
    # K=16, expected_a ~0.09, delta = 16*(1 - 0.09) = ~14.5
    assert 13 < u.elo_a_after - 1100 < 16


@pytest.mark.asyncio
async def test_record_match_result_is_idempotent(conn) -> None:
    """Re-applying the same match_id never double-counts."""
    now = datetime.now(UTC)

    # Set up a session row + two hypotheses in tournament
    await conn.execute(
        """INSERT INTO sessions(id, created_at, updated_at, status, research_goal,
                                 research_plan, config_snapshot, budget_tokens, budget_usd)
           VALUES ('ses_t', ?, ?, 'running', 'test', '{}', '{}', 1000000, 10.0)""",
        (now.isoformat(), now.isoformat()),
    )
    await conn.commit()

    for hid in ("hyp_x", "hyp_y"):
        h = Hypothesis(
            id=hid, session_id="ses_t", created_at=now,
            created_by="generation", strategy="literature",
            title="t", summary="s", full_text="f",
            artifact_path=f"artifacts/ses_t/hypotheses/{hid}.json",
            elo=1200, matches_played=0, state="in_tournament",
        )
        await hyp_repo.insert(conn, h)

    mid = ids.match_id("hyp_x", "hyp_y", "round1")
    m = TournamentMatch(
        id=mid, session_id="ses_t", created_at=now,
        hyp_a="hyp_x", hyp_b="hyp_y", mode="pairwise", winner="a",
        elo_a_before=1200.0, elo_b_before=1200.0,
        elo_a_after=1216.0, elo_b_after=1184.0, rationale="test",
    )
    await tourney_repo.insert_match(conn, m)

    kw = dict(
        match_id=mid, hyp_a="hyp_x", hyp_b="hyp_y", winner="a",
        k_new=32, k_warm=16, initial_elo=1200.0,
    )
    first = await tourney_repo.record_match_result(conn, **kw)
    assert first is not None
    assert first.elo_a_after == pytest.approx(1216.0)
    assert first.elo_b_after == pytest.approx(1184.0)

    # Re-apply: should no-op.
    assert await tourney_repo.record_match_result(conn, **kw) is None

    # State reflects exactly one update
    hx = await hyp_repo.fetch(conn, "hyp_x")
    hy = await hyp_repo.fetch(conn, "hyp_y")
    assert hx is not None and hy is not None
    assert hx.elo == pytest.approx(1216.0)
    assert hy.elo == pytest.approx(1184.0)
    assert hx.matches_played == 1
    assert hy.matches_played == 1
