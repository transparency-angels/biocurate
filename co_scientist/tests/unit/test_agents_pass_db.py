"""Agents hand their own DB connection to run_tool_loop (so search_library works)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from co_scientist.agents import evolution as evo_mod
from co_scientist.agents import generation as gen_mod
from co_scientist.agents import reflection as ref_mod
from co_scientist.agents.base import AgentDeps
from co_scientist.config import Config
from co_scientist.tools.registry import ToolRegistry


class _Stop(Exception):
    pass


def _session() -> SimpleNamespace:
    plan = SimpleNamespace(
        objective="o", preferences=["p"], idea_attributes=[], constraints=[],
    )
    return SimpleNamespace(id="ses_1", research_goal="g", research_plan=plan)


def _deps(sentinel: object) -> AgentDeps:
    cfg = Config()
    tools = ToolRegistry(cfg).discover()
    return AgentDeps(cfg=cfg, db=sentinel, llm=object(), tools=tools)  # type: ignore[arg-type]


def _spy(monkeypatch: pytest.MonkeyPatch, mod: object) -> dict:
    got: dict = {}

    async def fake_loop(*a, **kw):
        got.update(kw)
        raise _Stop

    monkeypatch.setattr(mod, "run_tool_loop", fake_loop)
    return got


async def _no_feedback(*a, **kw):
    return None


async def test_generation_passes_db(monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel = object()
    got = _spy(monkeypatch, gen_mod)

    async def fetch(db, sid):
        return _session()

    monkeypatch.setattr(gen_mod.sess_repo, "fetch", fetch)
    monkeypatch.setattr(gen_mod, "_latest_system_feedback", _no_feedback)
    task = SimpleNamespace(id="tsk_1", session_id="ses_1", payload={}, target_id=None)
    with pytest.raises(_Stop):
        await gen_mod.GenerationAgent(_deps(sentinel)).execute(task)
    assert got["db"] is sentinel


async def test_reflection_passes_db(monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel = object()
    got = _spy(monkeypatch, ref_mod)

    async def fetch_s(db, sid):
        return _session()

    async def fetch_h(db, hid):
        return SimpleNamespace(id="hyp_1", full_text="t")

    monkeypatch.setattr(ref_mod.sess_repo, "fetch", fetch_s)
    monkeypatch.setattr(ref_mod.hyp_repo, "fetch", fetch_h)
    task = SimpleNamespace(id="tsk_1", session_id="ses_1", payload={}, target_id="hyp_1")
    with pytest.raises(_Stop):
        await ref_mod.ReflectionAgent(_deps(sentinel)).execute(task)
    assert got["db"] is sentinel


async def test_evolution_passes_db(monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel = object()
    got = _spy(monkeypatch, evo_mod)
    agent = evo_mod.EvolutionAgent(_deps(sentinel))
    monkeypatch.setattr(agent, "_latest_feedback", _no_feedback)
    with pytest.raises(_Stop):
        await agent._run_and_persist(
            _session(), "prompt", strategy="out_of_box", mode_for_route="out_of_box",
            parent_ids=[],
        )
    assert got["db"] is sentinel
