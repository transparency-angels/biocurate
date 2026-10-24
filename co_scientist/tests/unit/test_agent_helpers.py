"""Tests for agent helper functions that don't require an LLM call."""

from __future__ import annotations

from co_scientist.agents.generation import _filter_to_seen_urls, _render_hypothesis_md
from co_scientist.agents.reflection import _render_review_md


def test_citation_url_filter_keeps_only_seen() -> None:
    citations = [
        {"title": "A", "url": "https://a.example/paper1"},
        {"title": "B", "url": "https://hallucinated.example/paper2"},
        {"title": "C", "url": "https://c.example/paper3"},
        {"no_url": True},
    ]
    seen = {"https://a.example/paper1", "https://c.example/paper3"}
    out = _filter_to_seen_urls(citations, seen)
    urls = {c["url"] for c in out}
    assert urls == seen
    # hallucinated URL is dropped
    assert "https://hallucinated.example/paper2" not in urls


def test_hypothesis_md_renders_sections() -> None:
    md = _render_hypothesis_md(
        {
            "title": "T",
            "statement": "S",
            "mechanism": "M",
            "entities": ["E1", "E2"],
            "anticipated_outcomes": "AO",
            "novelty_argument": "N",
            "citations": [
                {"title": "Paper", "url": "https://example.com/x", "year": 2024}
            ],
        }
    )
    for marker in ("# T", "**Hypothesis.** S", "## Mechanism", "## Entities",
                   "## Anticipated outcomes", "## Novelty", "## Citations",
                   "https://example.com/x"):
        assert marker in md


def test_review_md_renders_sections() -> None:
    md = _render_review_md(
        {
            "verdict": "missing_piece",
            "novelty": 0.7, "correctness": 0.5, "testability": 0.6,
            "assumptions": [
                {"assumption": "A1", "plausibility": "plausible", "rationale": "R1"}
            ],
            "evidence": [
                {"claim": "claim1", "url": "https://e.example/p", "excerpt": "quote"}
            ],
            "notes": "n",
        }
    )
    assert "Verdict" in md
    assert "novelty 0.70" in md
    assert "plausible" in md
    assert "https://e.example/p" in md
    assert "n" in md


def test_system_citation_policy_included_for_web_search_agents() -> None:
    from co_scientist.agents.base import BaseAgent
    from co_scientist.safety.quoting import SYSTEM_CITATION_POLICY

    for agent_name in ("generation", "reflection", "evolution"):
        agent = BaseAgent(deps=None)  # type: ignore
        agent.name = agent_name
        header = agent._system_prompt_header()
        assert SYSTEM_CITATION_POLICY in header
        assert "System Citation Policy:" in header
        assert "[Doc X, L#]" in header

    for agent_name in ("ranking", "proximity", "metareview"):
        agent = BaseAgent(deps=None)  # type: ignore
        agent.name = agent_name
        header = agent._system_prompt_header()
        assert SYSTEM_CITATION_POLICY not in header

