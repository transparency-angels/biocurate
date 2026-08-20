"""Tests for the session-facing MCP server.

This server is the plugin's whole surface: everything Claude Code or Codex can
do to a research session goes through these tools. The tests that matter are
the ones that protect the invariant the design rests on, namely that an
agent-authored review or match lands in the same tables, with the same Elo
math, as one the engine's own agents write.

Nothing here spawns a subprocess or spends a token.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from co_scientist import ids
from co_scientist.config import Config
from co_scientist.mcp.session_server import TOOL_SCHEMAS, SessionMcpServer
from co_scientist.models import Hypothesis, ResearchPlan, Session
from co_scientist.storage import db as db_mod
from co_scientist.storage.repos import hypotheses as hyp_repo
from co_scientist.storage.repos import sessions as sess_repo

pytestmark = pytest.mark.asyncio


# --------------------------------------------------------------------------- #
# fixtures


@pytest.fixture
def server(tmp_cfg: Config, monkeypatch: pytest.MonkeyPatch) -> SessionMcpServer:
    monkeypatch.delenv("COSCI_ALLOW_START", raising=False)
    monkeypatch.delenv("COSCI_CONFIG", raising=False)
    return SessionMcpServer(tmp_cfg)


async def _make_session(cfg: Config, goal: str = "why do cells do that") -> str:
    conn = await db_mod.connect(cfg)
    try:
        sid = ids.session_id()
        now = datetime.now(UTC)
        await sess_repo.insert(conn, Session(
            id=sid, created_at=now, updated_at=now, status="running",
            research_goal=goal, research_plan=ResearchPlan(objective=goal),
            config_snapshot={}, budget_tokens=1_000_000, budget_usd=10.0,
        ))
        return sid
    finally:
        await conn.close()


async def _make_hypothesis(
    cfg: Config, session_id: str, title: str, *, elo: float | None = None
) -> str:
    conn = await db_mod.connect(cfg)
    try:
        hid = ids.hypothesis_id(session_id, "generation", title)
        await hyp_repo.insert(conn, Hypothesis(
            id=hid, session_id=session_id, created_at=datetime.now(UTC),
            created_by="generation", strategy="literature",
            title=title, summary=f"{title} in three sentences.",
            full_text=f"# {title}\n\nDetail.", artifact_path=f"artifacts/{hid}.json",
            elo=elo, state="draft" if elo is None else "in_tournament",
        ))
        return hid
    finally:
        await conn.close()


async def call(server: SessionMcpServer, name: str, **args: Any) -> dict[str, Any]:
    """Invoke a tool the way the transport does and parse the JSON body."""
    result = await server.handle(name, args)
    body = json.loads(result["content"][0]["text"])
    body["_is_error"] = bool(result.get("isError"))
    return body


# --------------------------------------------------------------------------- #
# tool surface


async def test_every_declared_tool_has_a_handler(server: SessionMcpServer) -> None:
    for name in TOOL_SCHEMAS:
        assert hasattr(server, f"_t_{name}"), f"{name} is declared but not implemented"


async def test_tool_list_matches_schemas(server: SessionMcpServer) -> None:
    listed = {t["name"] for t in server.tool_list()}
    assert listed == set(TOOL_SCHEMAS)
    for tool in server.tool_list():
        assert tool["description"].strip()
        assert tool["inputSchema"]["type"] == "object"


async def test_unknown_tool_reports_what_is_available(server: SessionMcpServer) -> None:
    body = await call(server, "nope")
    assert body["_is_error"]
    assert "session_start" in body["available"]


# --------------------------------------------------------------------------- #
# reading


async def test_session_status_reports_counts_and_elo_spread(
    server: SessionMcpServer, tmp_cfg: Config
) -> None:
    sid = await _make_session(tmp_cfg)
    await _make_hypothesis(tmp_cfg, sid, "alpha", elo=1250.0)
    await _make_hypothesis(tmp_cfg, sid, "beta", elo=1150.0)
    await _make_hypothesis(tmp_cfg, sid, "gamma")

    body = await call(server, "session_status", session_id=sid)
    assert body["status"] == "running"
    assert body["hypothesis_states"] == {"draft": 1, "in_tournament": 2}
    assert body["elo"]["spread"] == pytest.approx(100.0)
    assert body["elo"]["ranked"] == 2
    assert body["has_overview"] is False


async def test_session_status_on_missing_session_is_an_error(
    server: SessionMcpServer,
) -> None:
    body = await call(server, "session_status", session_id="ses_nope")
    assert body["_is_error"]
    assert "no such session" in body["error"]


async def test_hypotheses_list_ranks_by_elo_and_paginates(
    server: SessionMcpServer, tmp_cfg: Config
) -> None:
    sid = await _make_session(tmp_cfg)
    await _make_hypothesis(tmp_cfg, sid, "low", elo=1100.0)
    await _make_hypothesis(tmp_cfg, sid, "high", elo=1300.0)
    await _make_hypothesis(tmp_cfg, sid, "mid", elo=1200.0)

    body = await call(server, "hypotheses_list", session_id=sid, limit=2)
    assert body["total"] == 3
    assert [h["title"] for h in body["hypotheses"]] == ["high", "mid"]

    page2 = await call(server, "hypotheses_list", session_id=sid, limit=2, offset=2)
    assert [h["title"] for h in page2["hypotheses"]] == ["low"]


async def test_hypothesis_get_returns_full_text_and_reviews(
    server: SessionMcpServer, tmp_cfg: Config
) -> None:
    sid = await _make_session(tmp_cfg)
    hid = await _make_hypothesis(tmp_cfg, sid, "alpha")
    await call(
        server, "review_record", hypothesis_id=hid, kind="full",
        body="Looks plausible.", verdict="neutral",
    )
    body = await call(server, "hypothesis_get", hypothesis_id=hid)
    assert body["hypothesis"]["full_text"].startswith("# alpha")
    assert len(body["reviews"]) == 1
    assert body["reviews"][0]["kind"] == "full"
    assert body["matches"] == []


async def test_overview_get_says_why_it_is_missing(
    server: SessionMcpServer, tmp_cfg: Config
) -> None:
    sid = await _make_session(tmp_cfg)
    body = await call(server, "overview_get", session_id=sid)
    assert body["_is_error"]
    assert "no final overview yet" in body["error"]


# --------------------------------------------------------------------------- #
# review_record


async def test_review_record_writes_a_row_and_an_artifact(
    server: SessionMcpServer, tmp_cfg: Config
) -> None:
    sid = await _make_session(tmp_cfg)
    hid = await _make_hypothesis(tmp_cfg, sid, "alpha")
    body = await call(
        server, "review_record", hypothesis_id=hid, kind="full",
        body="## Review\n\nNovel but the direction is backwards.",
        verdict="other_more_likely",
        scores={"novelty": 0.8, "correctness": 0.3},
        assumptions=[{
            "assumption": "FXR is antagonised",
            "plausibility": "implausible",
            "rationale": "Published data show agonism.",
        }],
        evidence=[{
            "claim": "Conjugated bile acids are protective",
            "url": "https://example.org/paper",
            "excerpt": "conjugated bile acids reduced inflammation",
        }],
    )
    assert not body["_is_error"]
    assert body["inserted"] is True
    assert body["state_promoted_to_reviewed"] is True

    conn = await db_mod.connect(tmp_cfg)
    try:
        async with conn.execute(
            "SELECT * FROM reviews WHERE id=?", (body["review_id"],)
        ) as cur:
            row = dict(await cur.fetchone())
        h = await hyp_repo.fetch(conn, hid)
    finally:
        await conn.close()

    assert row["session_id"] == sid            # session comes from the hypothesis
    assert row["verdict"] == "other_more_likely"
    assert row["novelty"] == pytest.approx(0.8)
    assert h is not None and h.state == "reviewed"
    assert (tmp_cfg.data_dir / body["artifact_path"]).exists()


async def test_review_record_rejects_evidence_without_an_excerpt(
    server: SessionMcpServer, tmp_cfg: Config
) -> None:
    sid = await _make_session(tmp_cfg)
    hid = await _make_hypothesis(tmp_cfg, sid, "alpha")
    body = await call(
        server, "review_record", hypothesis_id=hid, kind="full", body="x",
        evidence=[{"claim": "c", "url": "https://example.org"}],
    )
    assert body["_is_error"]
    assert "excerpt" in body["error"]


async def test_repeat_reviews_of_one_kind_get_distinct_ids(
    server: SessionMcpServer, tmp_cfg: Config
) -> None:
    sid = await _make_session(tmp_cfg)
    hid = await _make_hypothesis(tmp_cfg, sid, "alpha")
    first = await call(server, "review_record", hypothesis_id=hid, kind="full", body="one")
    second = await call(server, "review_record", hypothesis_id=hid, kind="full", body="two")
    assert first["review_id"] != second["review_id"]
    assert second["inserted"] is True


async def test_review_record_does_not_drag_a_ranked_hypothesis_backwards(
    server: SessionMcpServer, tmp_cfg: Config
) -> None:
    sid = await _make_session(tmp_cfg)
    hid = await _make_hypothesis(tmp_cfg, sid, "alpha", elo=1200.0)
    body = await call(server, "review_record", hypothesis_id=hid, kind="full", body="x")
    assert body["state_promoted_to_reviewed"] is False

    conn = await db_mod.connect(tmp_cfg)
    try:
        h = await hyp_repo.fetch(conn, hid)
    finally:
        await conn.close()
    assert h is not None and h.state == "in_tournament"


async def test_review_record_on_missing_hypothesis_is_an_error(
    server: SessionMcpServer,
) -> None:
    body = await call(server, "review_record", hypothesis_id="hyp_nope", kind="full", body="x")
    assert body["_is_error"]
    assert "no such hypothesis" in body["error"]


# --------------------------------------------------------------------------- #
# match_record


async def test_match_record_applies_a_zero_sum_elo_update(
    server: SessionMcpServer, tmp_cfg: Config
) -> None:
    sid = await _make_session(tmp_cfg)
    a = await _make_hypothesis(tmp_cfg, sid, "alpha", elo=1200.0)
    b = await _make_hypothesis(tmp_cfg, sid, "beta", elo=1200.0)

    body = await call(
        server, "match_record", hyp_a=a, hyp_b=b, winner="a",
        rationale="a survives its assumption check; b does not",
    )
    assert body["elo_applied"] is True
    assert body["elo"][a]["after"] > 1200.0
    assert body["elo"][b]["after"] < 1200.0
    assert body["elo"][a]["after"] - 1200.0 == pytest.approx(1200.0 - body["elo"][b]["after"])

    conn = await db_mod.connect(tmp_cfg)
    try:
        ha = await hyp_repo.fetch(conn, a)
        hb = await hyp_repo.fetch(conn, b)
        async with conn.execute("SELECT COUNT(*) AS n FROM elo_journal") as cur:
            journal = (await cur.fetchone())["n"]
    finally:
        await conn.close()
    assert ha is not None and hb is not None
    assert ha.elo == pytest.approx(body["elo"][a]["after"])
    assert ha.matches_played == 1 and hb.matches_played == 1
    assert journal == 1


async def test_match_record_is_idempotent_within_a_round(
    server: SessionMcpServer, tmp_cfg: Config
) -> None:
    sid = await _make_session(tmp_cfg)
    a = await _make_hypothesis(tmp_cfg, sid, "alpha", elo=1200.0)
    b = await _make_hypothesis(tmp_cfg, sid, "beta", elo=1200.0)

    first = await call(server, "match_record", hyp_a=a, hyp_b=b, winner="a", rationale="r")
    second = await call(server, "match_record", hyp_a=a, hyp_b=b, winner="a", rationale="r")
    assert first["elo_applied"] is True
    assert second["elo_applied"] is False
    assert "round" in second["note"]

    conn = await db_mod.connect(tmp_cfg)
    try:
        ha = await hyp_repo.fetch(conn, a)
    finally:
        await conn.close()
    assert ha is not None and ha.matches_played == 1


async def test_a_new_round_id_lets_the_same_pair_play_again(
    server: SessionMcpServer, tmp_cfg: Config
) -> None:
    sid = await _make_session(tmp_cfg)
    a = await _make_hypothesis(tmp_cfg, sid, "alpha", elo=1200.0)
    b = await _make_hypothesis(tmp_cfg, sid, "beta", elo=1200.0)
    await call(server, "match_record", hyp_a=a, hyp_b=b, winner="a", rationale="r")
    again = await call(
        server, "match_record", hyp_a=a, hyp_b=b, winner="b", rationale="r",
        round_id="rematch-after-new-evidence",
    )
    assert again["elo_applied"] is True


async def test_match_record_gives_an_unranked_hypothesis_its_starting_elo(
    server: SessionMcpServer, tmp_cfg: Config
) -> None:
    sid = await _make_session(tmp_cfg)
    a = await _make_hypothesis(tmp_cfg, sid, "alpha")          # no elo, state draft
    b = await _make_hypothesis(tmp_cfg, sid, "beta")
    body = await call(server, "match_record", hyp_a=a, hyp_b=b, winner="a", rationale="r")
    assert body["elo"][a]["before"] == pytest.approx(float(tmp_cfg.ranking.elo_initial))

    conn = await db_mod.connect(tmp_cfg)
    try:
        ha = await hyp_repo.fetch(conn, a)
    finally:
        await conn.close()
    assert ha is not None and ha.state == "in_tournament"


async def test_match_record_refuses_cross_session_and_self_pairs(
    server: SessionMcpServer, tmp_cfg: Config
) -> None:
    s1 = await _make_session(tmp_cfg, goal="one")
    s2 = await _make_session(tmp_cfg, goal="two")
    a = await _make_hypothesis(tmp_cfg, s1, "alpha")
    b = await _make_hypothesis(tmp_cfg, s2, "beta")

    cross = await call(server, "match_record", hyp_a=a, hyp_b=b, winner="a", rationale="r")
    assert cross["_is_error"] and "same session" in cross["error"]

    self_pair = await call(server, "match_record", hyp_a=a, hyp_b=a, winner="a", rationale="r")
    assert self_pair["_is_error"] and "different" in self_pair["error"]


# --------------------------------------------------------------------------- #
# feedback and lifecycle


async def test_feedback_pin_moves_the_hypothesis_state(
    server: SessionMcpServer, tmp_cfg: Config
) -> None:
    sid = await _make_session(tmp_cfg)
    hid = await _make_hypothesis(tmp_cfg, sid, "alpha")
    body = await call(
        server, "feedback_add", session_id=sid, text="keep this one", kind="pin", target=hid
    )
    assert not body["_is_error"]
    conn = await db_mod.connect(tmp_cfg)
    try:
        h = await hyp_repo.fetch(conn, hid)
    finally:
        await conn.close()
    assert h is not None and h.state == "pinned"


async def test_feedback_pin_without_a_target_is_refused(
    server: SessionMcpServer, tmp_cfg: Config
) -> None:
    sid = await _make_session(tmp_cfg)
    body = await call(server, "feedback_add", session_id=sid, text="x", kind="pin")
    assert body["_is_error"] and "target" in body["error"]


async def test_pause_and_abort_set_the_session_status(
    server: SessionMcpServer, tmp_cfg: Config
) -> None:
    sid = await _make_session(tmp_cfg)
    assert (await call(server, "session_pause", session_id=sid))["status"] == "paused"
    assert (await call(server, "session_abort", session_id=sid))["status"] == "aborted"


async def test_read_only_mode_refuses_to_start_or_resume(
    tmp_cfg: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COSCI_ALLOW_START", "0")
    server = SessionMcpServer(tmp_cfg)
    started = await call(server, "session_start", goal="anything")
    assert started["_is_error"] and "disabled" in started["error"]
    resumed = await call(server, "session_resume", session_id="ses_x")
    assert resumed["_is_error"] and "disabled" in resumed["error"]


async def test_session_start_refuses_when_the_backend_is_not_ready(
    server: SessionMcpServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "co_scientist.mcp.session_server._backend_ready",
        lambda cfg: (False, "no API key resolved"),
    )
    body = await call(server, "session_start", goal="anything")
    assert body["_is_error"]
    assert "not ready" in body["error"]


async def test_doctor_reports_the_backend_and_the_db(
    server: SessionMcpServer, tmp_cfg: Config
) -> None:
    body = await call(server, "doctor")
    assert body["db_path"] == str(tmp_cfg.db_path)
    assert body["db_exists"] is True
    assert body["session_start_allowed"] is True


# --------------------------------------------------------------------------- #
# hypothesis_record


async def test_hypothesis_record_adds_a_draft_the_engine_can_pick_up(
    server: SessionMcpServer, tmp_cfg: Config
) -> None:
    sid = await _make_session(tmp_cfg)
    body = await call(
        server, "hypothesis_record", session_id=sid,
        title="Transport-limited receptor engagement",
        summary="The metabolite is trapped in the lumen and never reaches the receptor.",
        full_text="# Mechanism\n\nStep one, step two.",
        strategy="literature",
        citations=[{"title": "A paper", "url": "https://example.org/a", "year": 2026}],
    )
    assert body["inserted"] is True
    assert body["created_by"] == "generation"
    assert body["state"] == "draft"

    conn = await db_mod.connect(tmp_cfg)
    try:
        h = await hyp_repo.fetch(conn, body["hypothesis_id"])
    finally:
        await conn.close()
    assert h is not None
    assert h.state == "draft" and h.elo is None
    assert (tmp_cfg.data_dir / body["artifact_path"]).exists()

    # Citations live in the artifact, matching where the engine's own agents
    # put them, and hypothesis_get surfaces them from there.
    fetched = await call(server, "hypothesis_get", hypothesis_id=body["hypothesis_id"])
    assert fetched["artifact"]["citations"][0]["url"] == "https://example.org/a"


async def test_hypothesis_record_with_parents_is_an_evolution(
    server: SessionMcpServer, tmp_cfg: Config
) -> None:
    sid = await _make_session(tmp_cfg)
    parent = await _make_hypothesis(tmp_cfg, sid, "alpha")
    body = await call(
        server, "hypothesis_record", session_id=sid, title="alpha, simplified",
        summary="Same mechanism with the receptor claim removed.",
        full_text="# Simplified", strategy="simplify", parent_ids=[parent],
    )
    assert body["created_by"] == "evolution"

    conn = await db_mod.connect(tmp_cfg)
    try:
        h = await hyp_repo.fetch(conn, body["hypothesis_id"])
    finally:
        await conn.close()
    assert h is not None and h.parent_ids == [parent]


async def test_hypothesis_record_refuses_an_unknown_parent(
    server: SessionMcpServer, tmp_cfg: Config
) -> None:
    sid = await _make_session(tmp_cfg)
    body = await call(
        server, "hypothesis_record", session_id=sid, title="t", summary="s",
        full_text="f", strategy="combine", parent_ids=["hyp_nope"],
    )
    assert body["_is_error"] and "parent hypothesis does not exist" in body["error"]


async def test_hypothesis_record_is_idempotent_on_the_same_summary(
    server: SessionMcpServer, tmp_cfg: Config
) -> None:
    sid = await _make_session(tmp_cfg)
    args = dict(
        session_id=sid, title="t", summary="one specific mechanism, stated once",
        full_text="f", strategy="literature",
    )
    first = await call(server, "hypothesis_record", **args)
    second = await call(server, "hypothesis_record", **args)
    assert first["hypothesis_id"] == second["hypothesis_id"]
    assert second["inserted"] is False
