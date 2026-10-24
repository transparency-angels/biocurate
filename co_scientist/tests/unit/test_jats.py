"""Unit tests for the offline JATS parser and passage splitter."""

from __future__ import annotations

from pathlib import Path

import pytest

from co_scientist.library.jats import parse_jats

FIXTURES = Path(__file__).parent.parent / "fixtures" / "jats"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_jats_figure_and_table_anchors():
    _, passages = parse_jats(_load("with_ids.xml"), "PMC1234567")
    by_anchor = {p.anchor_id: p for p in passages}
    fig = by_anchor["PMC1234567#F1"]
    assert fig.kind == "figure"
    assert fig.label == "Figure 1"
    assert fig.text.startswith("Figure 1 ")
    assert "XYZ knockdown restores sensitivity." in fig.text
    tab = by_anchor["PMC1234567#T1"]
    assert tab.kind == "table"
    assert tab.text.startswith("Table 1 ")
    assert "Origin as reported by the supplier." in tab.text
    assert [p.ordinal for p in passages] == list(range(len(passages)))


def test_parse_jats_fallback_anchors_are_stable():
    _, first = parse_jats(_load("no_ids.xml"), "PMC7654321")
    _, second = parse_jats(_load("no_ids.xml"), "PMC7654321")
    assert [p.anchor_id for p in first] == [p.anchor_id for p in second]
    anchors = [p.anchor_id for p in first]
    assert anchors[:2] == ["PMC7654321#abstract.p1", "PMC7654321#abstract.p2"]
    assert "PMC7654321#s0.p1" in anchors
    assert "PMC7654321#s2.p2" in anchors
    nested = next(p for p in first if p.anchor_id == "PMC7654321#s2.p2")
    assert nested.section == "Results > Subsection"
    assert nested.text == "Nested paragraph with emphasis and a citation 1."
    orphan = next(p for p in first if p.anchor_id == "PMC7654321#s0.p1")
    assert orphan.section == ""
    # A caption-less table is kept, text is the label alone.
    table = next(p for p in first if p.kind == "table")
    assert table.anchor_id == "PMC7654321#T9"
    assert table.text == "Table 9"


def test_parse_jats_splits_long_paragraph():
    _, passages = parse_jats(_load("with_ids.xml"), "PMC1234567", max_chars=200)
    parts = [p for p in passages if p.anchor_id.startswith("PMC1234567#P3.")]
    assert [p.anchor_id.rsplit(".", 1)[1] for p in parts][:2] == ["1", "2"]
    assert all(len(p.text) <= 200 for p in passages)


def test_parse_jats_hard_splits_oversized_sentence():
    xml = "<article><body><p>" + "word " * 100 + "</p></body></article>"
    _, passages = parse_jats(xml, "PMC1", max_chars=50)
    assert len(passages) > 1
    assert all(len(p.text) <= 50 for p in passages)
    assert " ".join(p.text for p in passages) == ("word " * 100).strip()


def test_parse_jats_skips_references():
    _, passages = parse_jats(_load("with_ids.xml"), "PMC1234567")
    joined = " ".join(p.text for p in passages)
    assert "Smith J." not in joined
    assert "core facility" not in joined
    assert "must be skipped" not in joined


def test_parse_jats_meta():
    meta, _ = parse_jats(_load("with_ids.xml"), "PMC1234567")
    assert meta.pmcid == "PMC1234567"
    assert meta.title == "Kinase XYZ drives resistance in tumour cells"
    assert meta.doi == "10.1000/test.2021.001"
    assert meta.year == 2021
    assert meta.journal == "Nature Testing"


def test_parse_jats_invalid_xml_raises_value_error():
    with pytest.raises(ValueError, match="JATS"):
        parse_jats("<article><oops>", "PMC1")
