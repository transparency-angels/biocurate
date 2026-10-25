"""The `dataAnalysis` block: survival verdict, curves, caveats, related findings."""

from __future__ import annotations

import pytest
from lifelines import KaplanMeierFitter

from co_scientist.web.data_view import _nice_ticks, data_analysis, kaplan_meier

KEY = "EGFR|mutation|ERLOTINIB"


def _candidate(**over) -> dict:
    c = {
        "candidate_key": KEY, "biomarker": "EGFR", "alteration_type": "mutation",
        "drug": "ERLOTINIB", "delta_os_months": -6.2, "median_os_altered": 8.1,
        "median_os_wt": 14.3, "p_value": 0.001, "q_value": 0.02,
        "altered_samples": 40, "unaltered_samples": 60, "altered_events": 30,
        "unaltered_events": 35, "altered_censored": 10, "unaltered_censored": 25,
        "hazard_ratio": 1.9, "hr_ci_lower": 1.2, "hr_ci_upper": 3.0,
        "test_method": "lifelines.statistics.logrank_test",
        "survival_estimator": "lifelines.KaplanMeierFitter", "cohort": "Clinical cohort",
    }
    c.update(over)
    return c


def _report(**over) -> dict:
    r = {
        "candidates": [_candidate()],
        "methods": {"alpha": 0.05, "significance_rule": "BH q <= alpha",
                    "multiple_testing_correction": "Benjamini-Hochberg"},
        "selection": {"eligible_tests": 5400},
        "endpoint": {"label": "Overall survival", "unit": "months",
                     "duration_column": "OS_MONTHS", "event_column": "OS_STATUS"},
        "software": {"python": "3.11.9", "lifelines": "0.30.0"},
        "inputs": {"metadata": {"path": "/tmp/x/clinical.csv", "sha256": "a" * 64}},
    }
    r.update(over)
    return r


def _points() -> list[dict]:
    pts = [{"sample_id": f"A{i}", "group": "altered", "value": float(1 + i),
            "event": int(i % 3 != 0)} for i in range(12)]
    pts += [{"sample_id": f"U{i}", "group": "unaltered", "value": float(2 + 2 * i),
             "event": int(i % 4 != 0)} for i in range(12)]
    return pts


def test_kaplan_meier_matches_lifelines() -> None:
    times = [1, 2, 2, 3, 4, 5, 5, 6, 8, 9, 11, 12]
    events = [1, 0, 1, 1, 0, 1, 1, 0, 1, 1, 0, 1]
    ours = kaplan_meier(times, events)
    ref = KaplanMeierFitter(alpha=0.05).fit(times, event_observed=events)
    for step in ours["steps"][1:]:
        assert step["s"] == pytest.approx(float(ref.survival_function_at_times(step["t"]).iloc[0]),
                                          abs=1e-4)
        ci = ref.confidence_interval_.loc[step["t"]]
        if 0 < step["s"] < 1:
            assert step["lower"] == pytest.approx(float(ci.iloc[0]), abs=1e-3)
            assert step["upper"] == pytest.approx(float(ci.iloc[1]), abs=1e-3)
    assert ours["steps"][0] == {"t": 0.0, "s": 1.0, "lower": 1.0, "upper": 1.0}
    assert sorted(ours["censored"]) == [2.0, 4.0, 6.0, 11.0]


def test_supported_survival_candidate() -> None:
    out = data_analysis(_candidate(), _points(), _report(), "text")
    assert out["kind"] == "survival" and out["status"] == "supported"
    assert "shorter" in out["headline"] and "EGFR mutation" in out["headline"]
    assert out["effect"]["direction"] == "worse"
    assert out["effect"]["hazardRatio"] == 1.9
    assert out["significance"] == {"pValue": 0.001, "qValue": 0.02, "alpha": 0.05,
                                   "testsRun": 5400}
    assert [g["group"] for g in out["groups"]] == ["altered", "unaltered"]
    assert [c["group"] for c in out["curves"]] == ["altered", "unaltered"]
    assert out["atRisk"][0] == {"t": 0.0, "altered": 12, "unaltered": 12}
    labels = {m["label"] for m in out["methods"]}
    assert {"Comparison", "Endpoint", "Multiple testing", "Software"} <= labels
    inputs = next(m for m in out["methods"] if m["label"] == "Input: metadata")
    assert inputs["value"].startswith("clinical.csv") and "/tmp" not in inputs["value"]


def test_nominal_when_fdr_fails_and_caveat_says_so() -> None:
    out = data_analysis(_candidate(q_value=0.2), _points(), _report(), "")
    assert out["status"] == "nominal"
    assert any("5400 comparisons" in c["text"] for c in out["caveats"])


def test_legacy_report_without_q_is_nominal() -> None:
    out = data_analysis(_candidate(q_value=None), _points(), _report(), "")
    assert out["status"] == "nominal"


def test_caveats_flag_small_groups_few_events_censoring_and_nr_median() -> None:
    c = _candidate(altered_samples=12, altered_events=4, altered_censored=8,
                   median_os_altered=None, delta_os_months=None)
    texts = " ".join(x["text"] for x in data_analysis(c, _points(), _report(), "")["caveats"])
    assert "Small group" in texts and "Few events (4)" in texts
    assert "67% of" in texts and "not reached" in texts
    assert "Unadjusted" in texts and "Association, not causation" in texts


def test_points_without_events_fall_back_to_stored_curves() -> None:
    legacy = [{k: v for k, v in p.items() if k != "event"} for p in _points()]
    curve = {"association": {"candidate_key": KEY}}
    for g in ("altered", "unaltered"):
        curve[g] = {"timeline": [0.0, 2.0, 5.0], "survival_probability": [1.0, 0.8, 0.5],
                    "ci_lower": [1.0, 0.6, 0.3], "ci_upper": [1.0, 0.9, 0.7],
                    "censored": [0, 1, 0], "removed": [0, 2, 1], "at_risk": [10, 10, 8]}
    out = data_analysis(_candidate(), legacy, _report(survival_curves=[curve]), "")
    assert [c["group"] for c in out["curves"]] == ["altered", "unaltered"]
    assert out["curves"][0]["censored"] == [2.0]
    assert out["atRisk"][0]["altered"] == 10


def test_no_curves_when_neither_events_nor_stored_curves() -> None:
    legacy = [{k: v for k, v in p.items() if k != "event"} for p in _points()]
    out = data_analysis(_candidate(), legacy, _report(), "")
    assert out["curves"] == [] and out["atRisk"] == []
    assert out["status"] == "supported"


def test_no_dataset_is_not_tested() -> None:
    out = data_analysis(None, [], None, "anything")
    assert out["status"] == "not_tested" and out["kind"] == "none"
    assert out["relatedFindings"] == [] and out["curves"] == []


def test_exploratory_report_lists_related_findings_only_for_named_columns() -> None:
    report = {
        "profile_type": "exploratory_tabular",
        "group_comparisons": [
            {"table": "t", "group": "treatment_arm", "measure": "tumour_volume",
             "groups": [{"name": "A", "n": 10, "median": 3.0}, {"name": "B", "n": 9, "median": 5.0}],
             "test": "Mann-Whitney U", "effect_size": 0.4,
             "effect_size_name": "rank-biserial correlation", "p_value": 0.01, "q_value": 0.03},
            {"table": "t", "group": "site", "measure": "weight", "groups": [],
             "test": "Mann-Whitney U", "effect_size": 0.1,
             "effect_size_name": "rank-biserial correlation", "p_value": 0.5, "q_value": 0.6},
        ],
        "correlations": [{"table": "t", "x": "dose", "y": "tumour_volume", "n": 19,
                          "rho": -0.6, "p_value": 0.002, "q_value": 0.01}],
    }
    out = data_analysis(None, [], report, "Higher dose shrinks tumour volume in arm A.")
    assert out["kind"] == "exploratory" and out["status"] == "not_tested"
    titles = [f["title"] for f in out["relatedFindings"]]
    assert titles == ["dose and tumour_volume", "tumour_volume by treatment_arm"]
    assert out["caveats"] and "not a test" in out["caveats"][0]["text"]


def test_nice_ticks() -> None:
    assert _nice_ticks(37) == [0.0, 10.0, 20.0, 30.0]
    assert _nice_ticks(0) == [0.0]
