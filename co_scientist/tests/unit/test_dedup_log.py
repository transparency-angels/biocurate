"""Generation/Evolution log (ids and cosine only, no text) when dedup flags a duplicate."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
from structlog.testing import capture_logs

from co_scientist.agents import evolution as evo_mod
from co_scientist.agents import generation as gen_mod
from co_scientist.config import Config


class _Embedder:
    model, dim = "m", 4

    async def embed(self, texts):
        return np.array([[1.0, 0, 0, 0]], dtype="float32")


class _Store:
    def __init__(self, nearest):
        self._nearest = nearest

    async def load_or_create(self):
        pass

    async def search(self, vec, k):
        return self._nearest


def _agent(cls):
    return cls.__new__(cls)  # only `.deps.cfg` / `.deps.db` are used by _dedup_query


@pytest.mark.parametrize("mod,cls", [(gen_mod, "GenerationAgent"), (evo_mod, "EvolutionAgent")])
async def test_duplicate_is_logged_with_ids_and_cosine(monkeypatch, mod, cls) -> None:
    monkeypatch.setattr(mod, "make_embedder", lambda cfg: _Embedder())
    monkeypatch.setattr(mod, "make_vector_store", lambda *a, **k: _Store([("hyp_old", 0.97)]))
    agent = _agent(getattr(mod, cls))
    agent.deps = SimpleNamespace(cfg=Config(), db=object())
    with capture_logs() as logs:
        dup, payload = await agent._dedup_query(
            "ses_1", "secret hypothesis text", hypothesis_id="hyp_new"
        )
    assert dup == "hyp_old" and payload is None
    rec = [r for r in logs if r["event"] == "dedup_duplicate_found"]
    assert len(rec) == 1
    assert rec[0]["hypothesis_id"] == "hyp_new"
    assert rec[0]["duplicate_of"] == "hyp_old"
    assert rec[0]["cosine"] == pytest.approx(0.97)
    assert "secret" not in str(rec[0])


async def test_no_log_when_nothing_is_near(monkeypatch) -> None:
    monkeypatch.setattr(gen_mod, "make_embedder", lambda cfg: _Embedder())
    monkeypatch.setattr(gen_mod, "make_vector_store", lambda *a, **k: _Store([("x", 0.1)]))
    agent = _agent(gen_mod.GenerationAgent)
    agent.deps = SimpleNamespace(cfg=Config(), db=object())
    with capture_logs() as logs:
        dup, payload = await agent._dedup_query("ses_1", "t", hypothesis_id="hyp_new")
    assert dup is None and payload is not None
    assert not [r for r in logs if r["event"] == "dedup_duplicate_found"]
