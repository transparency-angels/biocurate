"""Pure mapping from stored hypotheses to the React app's `ResearchSession`."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from co_scientist.models import Hypothesis
from co_scientist.models.hypothesis import CitedPaper
from co_scientist.web import research_view as rv

# Copied from frontend/src/types/research.ts.
RESEARCH_SESSION_KEYS = {"id", "isDemo", "hypotheses"}
HYPOTHESIS_KEYS = {
    "id", "rank", "title", "summary", "abstract", "explanation",
    "dataSummary", "dataPoints", "sources",
}
SOURCE_KEYS = {"id", "title", "publication", "year", "evidenceType", "description", "url"}
DATA_POINT_KEYS = {"id", "label", "group", "value"}
DATA_SUMMARY_KEYS = {"description", "metric", "unit"}
EVIDENCE_TYPES = {"Experimental study", "Dataset", "Review", "Clinical study"}

KEY = "EGFR|mutation|ERLOTINIB"


def _hyp(
    title: str, *, state: str = "in_tournament", elo: float | None = 1200.0,
    citations: list[CitedPaper] | None = None, data_evidence: dict | None = None,
    full_text: str | None = None,
) -> Hypothesis:
    return Hypothesis(
        id=f"hyp_{title}", session_id="ses_x", created_at=datetime.now(UTC),
        created_by="generation", strategy="literature", title=title,
        summary=f"{title} summary.",
        full_text=full_text if full_text is not None else f"# {title}\n\nFirst.\n\nSecond.",
        citations=citations or [], data_evidence=data_evidence,
        artifact_path="x.json", elo=elo, state=state,
    )


def _points() -> dict[str, dict[str, Any]]:
    return {KEY: {"metric": "os_months", "unit": "months", "points": [
        {"sample_id": "S1", "group": "altered", "value": 3.5},
        {"sample_id": "S2", "group": "unaltered", "value": 12.0},
    ]}}


def test_shape_matches_frontend_types() -> None:
    h = _hyp(
        "a",
        citations=[CitedPaper(title="T", url="https://example.org/p", excerpt="x", year=2020)],
        data_evidence={"candidate_key": KEY, "biomarker": "EGFR", "drug": "ERLOTINIB"},
    )
    out = rv.to_research_session("ses_x", [h], None, _points())
    assert set(out) == RESEARCH_SESSION_KEYS
    assert out["id"] == "ses_x" and out["isDemo"] is False
    (hyp,) = out["hypotheses"]
    assert set(hyp) == HYPOTHESIS_KEYS
    assert set(hyp["dataSummary"]) == DATA_SUMMARY_KEYS
    assert all(set(p) == DATA_POINT_KEYS for p in hyp["dataPoints"])
    assert all(set(s) == SOURCE_KEYS for s in hyp["sources"])
    assert hyp["sources"][0]["evidenceType"] in EVIDENCE_TYPES
    assert hyp["dataPoints"] == [
        {"id": "S1", "label": "S1", "group": "altered", "value": 3.5},
        {"id": "S2", "label": "S2", "group": "unaltered", "value": 12.0},
    ]
    assert hyp["dataSummary"]["metric"] == "os_months"
    assert hyp["dataSummary"]["unit"] == "months"
    assert "EGFR" in hyp["dataSummary"]["description"]


def test_no_dataset_gives_empty_summary_and_points() -> None:
    (hyp,) = rv.to_research_session("ses_x", [_hyp("a")], None, {})["hypotheses"]
    assert hyp["dataPoints"] == []
    assert hyp["dataSummary"] == {"description": "", "metric": "", "unit": ""}


def test_abstract_is_first_paragraph_and_explanation_the_rest() -> None:
    h = _hyp("a", full_text="# Title\n\n**Hypothesis.** It works.\n\n## Mechanism\nBecause.\n\nMore.")
    (hyp,) = rv.to_research_session("ses_x", [h], None, {})["hypotheses"]
    assert hyp["abstract"] == "**Hypothesis.** It works."
    assert hyp["explanation"] == "## Mechanism\nBecause.\n\nMore."


def test_selection_and_rank() -> None:
    hyps = [
        _hyp("low", elo=1100.0), _hyp("pinned", state="pinned", elo=None),
        _hyp("high", elo=1300.0), _hyp("rej", state="rejected", elo=1500.0),
        _hyp("quar", state="quarantined", elo=1400.0), _hyp("ret", state="retired"),
        _hyp("rev", state="reviewed", elo=None), _hyp("draft", state="draft"),
    ]
    out = rv.to_research_session("ses_x", hyps, None, {})["hypotheses"]
    assert [h["title"] for h in out] == ["high", "low", "pinned"]
    assert [h["rank"] for h in out] == [1, 2, 3]


def test_reviewed_shown_before_tournament_starts() -> None:
    hyps = [_hyp("rev", state="reviewed", elo=None), _hyp("pin", state="pinned", elo=1250.0),
            _hyp("draft", state="draft")]
    out = rv.to_research_session("ses_x", hyps, None, {})["hypotheses"]
    assert [h["title"] for h in out] == ["pin", "rev"]


def test_linked_candidate_keys_only_for_selected() -> None:
    hyps = [
        _hyp("a", data_evidence={"candidate_key": KEY}),
        _hyp("b", state="rejected", data_evidence={"candidate_key": "X|y|Z"}),
        _hyp("c", data_evidence={"biomarker": "KRAS", "alteration_type": "mutation",
                                 "drug": "DRUG"}),
    ]
    assert rv.linked_candidate_keys(rv.select_hypotheses(hyps)) == [KEY, "KRAS|mutation|DRUG"]


def _source(c: CitedPaper, **kw: Any) -> dict[str, Any]:
    (hyp,) = rv.to_research_session("ses_x", [_hyp("a", citations=[c])], None, {}, **kw)[
        "hypotheses"
    ]
    return hyp["sources"][0]


def test_publication_and_evidence_type_derivation() -> None:
    web = _source(CitedPaper(title="Mouse knockout study", url="https://www.nature.com/a"))
    assert web["publication"] == "www.nature.com"
    assert web["evidenceType"] == "Experimental study"
    assert web["url"] == "https://www.nature.com/a"

    review = _source(CitedPaper(title="A systematic Review of X", url="https://x.org/r"))
    assert review["evidenceType"] == "Review"
    meta = _source(CitedPaper(title="Meta-analysis of Y", url="https://x.org/m"))
    assert meta["evidenceType"] == "Review"
    trial = _source(CitedPaper(title="Phase III trial in patients", url="https://x.org/t"))
    assert trial["evidenceType"] == "Clinical study"

    lib_url = "https://europepmc.org/article/PMC/PMC42#abstract.p1"
    lib = _source(CitedPaper(title="Plain title", url=lib_url, year=2021),
                  journals={"PMC42": "Annual Reviews of Oncology"})
    assert lib["publication"] == "Annual Reviews of Oncology"
    assert lib["evidenceType"] == "Review"  # journal matches the review pattern
    assert lib["year"] == 2021


def test_upload_citations_have_null_url_and_dataset_type() -> None:
    doc = _source(CitedPaper(title="notes.pdf", url="upload://att_DOC#p3", excerpt="quote"),
                  attachments={"att_DOC": ("notes.pdf", "document")})
    assert doc["url"] is None
    assert doc["publication"] == "notes.pdf"
    assert doc["description"] == "quote"
    assert doc["evidenceType"] == "Experimental study"
    tab = _source(CitedPaper(title="clinical.csv", url="upload://att_TAB#r1"),
                  attachments={"att_TAB": ("clinical.csv", "tabular")})
    assert tab["url"] is None and tab["evidenceType"] == "Dataset"


def test_non_http_urls_are_not_links() -> None:
    assert _source(CitedPaper(title="t", url="javascript:alert(1)"))["url"] is None


def test_library_pmcid_parses_passage_urls_only() -> None:
    assert rv.library_pmcid("https://europepmc.org/article/PMC/PMC42#F1") == "PMC42"
    assert rv.library_pmcid("https://example.org/PMC42") is None
    assert rv.library_pmcid("upload://att_1#p1") is None
