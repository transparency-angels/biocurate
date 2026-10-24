#!/usr/bin/env python3
"""Standalone verification script for line-level citation support ([S#, L#-L#]) in metareview.

Tests:
1. MetaReviewAgent._extract_line_range on various excerpt formats.
2. MetaReviewAgent._source_block formatting with line numbers.
3. MetaReviewAgent.extract_citations parsing [S#, L#-L#], [S#, L#], and [S#].
4. Prompts (metareview_final.md, metareview_system.md) citation instructions.
5. SYSTEM_CITATION_POLICY formatting.
6. CitationVerifier._normalize stripping line-level citation prefixes.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

# Add workspace to sys.path
WORKSPACE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKSPACE))

# Lightweight mock finder for third-party libraries (pydantic, ulid, jinja2)
# allowing this verification to run standalone in any standard Python environment.
class DummyBase:
    def __init_subclass__(cls, **kw):
        pass

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)

    def model_copy(self, update=None):
        d = dict(self.__dict__)
        if update:
            d.update(update)
        return DummyBase(**d)

class AutoMock(types.ModuleType):
    def __init__(self, name):
        super().__init__(name)
    def __getattr__(self, name):
        if name in ("BaseModel", "BaseSettings"):
            return DummyBase
        sub = AutoMock(name)
        setattr(self, name, sub)
        return sub
    def __call__(self, *args, **kwargs):
        return AutoMock("call_result")

class MockFinder:
    def find_spec(self, fullname, path, target=None):
        top = fullname.split(".")[0]
        if top == "co_scientist" or top in sys.stdlib_module_names:
            return None
        return importlib.util.spec_from_loader(fullname, self)
    def create_module(self, spec):
        return AutoMock(spec.name)
    def exec_module(self, module):
        pass

sys.meta_path.insert(0, MockFinder())

# Imported after the module mocks above are installed on sys.meta_path.
from co_scientist.agents.metareview import MetaReviewAgent  # noqa: E402
from co_scientist.models.hypothesis import CitedPaper  # noqa: E402
from co_scientist.models.review import Evidence  # noqa: E402


def test_extract_line_range():
    print("=" * 70)
    print("1. MetaReviewAgent._extract_line_range")
    print("=" * 70)

    cases = [
        ("[L1] Short-chain fatty acids", "L1"),
        ("[L3] First sentence.\n[L4] Second sentence.\n[L5] Third sentence.", "L3-L5"),
        ("[L12] Solitary line", "L12"),
        ("Evidence spanning L1-L10 in the document", "L1-L10"),
        ("[L2-L8] Pre-formatted range", "L2-L8"),
        ("Plain text without any line numbers", None),
        ("", None),
    ]

    for text, expected in cases:
        got = MetaReviewAgent._extract_line_range(text)
        assert got == expected, f"Expected {expected!r}, got {got!r} for {text!r}"
        print(f"  PASS: {text[:45]!r:<48} -> {got}")


def test_source_block_formatting():
    print("\n" + "=" * 70)
    print("2. MetaReviewAgent._source_block with line-level tags")
    print("=" * 70)

    hyps = [
        DummyBase(
            id="hyp_01",
            citations=[
                CitedPaper(
                    title="Short-chain fatty acids: linking diet, the microbiome and immunity",
                    url="https://pubmed.ncbi.nlm.nih.gov/38565643/",
                    excerpt="[L1] The short-chain fatty acids (SCFAs) butyrate...\n[L2] SCFAs regulate mucosal immunity\n[L3] The anti-inflammatory role...",
                )
            ],
        )
    ]
    reviews = [
        DummyBase(
            hypothesis_id="hyp_01",
            evidence=[
                Evidence(
                    claim="Gut-Heart Axis in Cardiovascular Disease",
                    url="https://europepmc.org/article/MED/42794738",
                    excerpt="[L12] Microbial metabolites exert various important effects on cardiovascular physiology.",
                )
            ],
        )
    ]

    block = MetaReviewAgent._source_block(hyps, reviews)
    print(block)
    assert "- [S1] Short-chain fatty acids" in block
    assert "(lines: L1-L3)" in block
    assert "https://pubmed.ncbi.nlm.nih.gov/38565643/" in block
    assert "- [S2] Gut-Heart Axis" in block
    assert "(lines: L12)" in block
    assert "https://europepmc.org/article/MED/42794738" in block
    print("\n  PASS: _source_block correctly formats [S1] (lines: L1-L3) and [S2] (lines: L12)")


def test_extract_citations():
    print("\n" + "=" * 70)
    print("3. MetaReviewAgent.extract_citations ([S#, L#-L#])")
    print("=" * 70)

    overview_sample = """
# Main research directions
## Direction 1: SCFA-Mediated Barrier Defense
SCFAs promote epithelial integrity through GPCR signalling [S1, L1-L3].
Microbial acetate and butyrate directly modulate systemic vascular tone [S2, L12].
In vitro validation shows distinct concentration dependence [S1, L2], supporting earlier findings [S3].
"""

    cites = MetaReviewAgent.extract_citations(overview_sample)
    for c in cites:
        print(f"  Found citation: {c['raw']:<16} => Source: {c['source']}, Lines: {c['line_range']}")

    assert len(cites) == 4
    assert cites[0] == {
        "raw": "[S1, L1-L3]",
        "source": "S1",
        "source_idx": 1,
        "start_line": 1,
        "end_line": 3,
        "line_range": "L1-L3",
    }
    assert cites[1] == {
        "raw": "[S2, L12]",
        "source": "S2",
        "source_idx": 2,
        "start_line": 12,
        "end_line": 12,
        "line_range": "L12",
    }
    assert cites[2] == {
        "raw": "[S1, L2]",
        "source": "S1",
        "source_idx": 1,
        "start_line": 2,
        "end_line": 2,
        "line_range": "L2",
    }
    assert cites[3] == {
        "raw": "[S3]",
        "source": "S3",
        "source_idx": 3,
        "start_line": None,
        "end_line": None,
        "line_range": None,
    }
    print("  PASS: extract_citations parsed all [S#, L#-L#], [S#, L#], and [S#] citations.")


def test_prompts_and_policies():
    print("\n" + "=" * 70)
    print("4. Prompt templates & System Citation Policy")
    print("=" * 70)

    final_prompt = (WORKSPACE / "config" / "prompts" / "metareview_final.md").read_text(encoding="utf-8")
    assert "[S#, L#-L#]" in final_prompt
    print("  PASS: metareview_final.md mandates [S#, L#-L#] format.")

    system_prompt = (WORKSPACE / "config" / "prompts" / "metareview_system.md").read_text(encoding="utf-8")
    assert "[S#, L#-L#]" in system_prompt
    print("  PASS: metareview_system.md mandates [S#, L#-L#] format.")

    from co_scientist.safety.quoting import SYSTEM_CITATION_POLICY
    assert "[S#, L#-L#]" in SYSTEM_CITATION_POLICY
    assert "[Doc X, L#]" in SYSTEM_CITATION_POLICY
    print("  PASS: SYSTEM_CITATION_POLICY aligns with [S#, L#-L#].")

    from co_scientist.safety.citation_verifier import _normalize
    norm = _normalize("[S1, L3-L5] The anti-inflammatory role of butyrate")
    assert norm == "the anti-inflammatory role of butyrate"
    print(f"  PASS: CitationVerifier._normalize stripped line/source tag prefix cleanly: {norm!r}")


def main():
    test_extract_line_range()
    test_source_block_formatting()
    test_extract_citations()
    test_prompts_and_policies()
    print("\n" + "=" * 70)
    print("ALL VERIFICATIONS PASSED: Citation format is now [S#, L#-L#]")
    print("=" * 70)


if __name__ == "__main__":
    main()

