"""Validate censored survival estimates independently of agent orchestration."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from lifelines import KaplanMeierFitter
from lifelines.statistics import logrank_test
from PIL import Image

from co_scientist.analysis import profile_dataset
from co_scientist.analysis import tests_csv as export_tests_csv
from co_scientist.survival_plots import survival_plot_images
from scripts.validate_data_analysis import compare_reference, main


@pytest.fixture
def cohort(tmp_path: Path) -> Path:
    with (tmp_path / "clinical.csv").open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["sample_id", "drug", "os_months", "event"])
        for i in range(40):
            # Censoring at times 2 and 4 gives S(1)=.75, S(2)=.75,
            # S(3)=.375, S(4)=.375 in the altered group; KM median=3.
            time = (i % 4 + 1) * (1 if i < 20 else 10)
            writer.writerow([f"S{i}", "DRUG_A", time, int(i % 2 == 0)])
    with (tmp_path / "mutations.csv").open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["sample_id", "DURATION", "EVENT_ONLY", "UNDERPOWERED"])
        for i in range(40):
            writer.writerow([f"S{i}", int(i < 20), int(i % 2 == 0), int(i < 9)])
    return tmp_path


def _reference(report: dict) -> dict:
    return json.loads(json.dumps({key: report[key] for key in ("sample_count", "drugs", "candidates", "methods")}))


def test_survival_statistics_match_independent_vectors(cohort: Path) -> None:
    report = profile_dataset(cohort, target_drugs=["DRUG_A"])
    assert report["sample_count"] == 40
    assert report["selection"]["eligible_tests"] == 2
    assert "UNDERPOWERED" not in {test["biomarker"] for test in report["tests"]}
    candidate = next(test for test in report["tests"] if test["biomarker"] == "DURATION")
    altered = [1, 2, 3, 4] * 5
    unaltered = [10, 20, 30, 40] * 5
    events = [1, 0, 1, 0] * 5
    oracle = logrank_test(altered, unaltered, event_observed_A=events, event_observed_B=events)
    assert candidate["logrank_statistic"] == pytest.approx(oracle.test_statistic)
    assert candidate["p_value"] == pytest.approx(oracle.p_value, rel=1e-12, abs=0)
    assert candidate["median_os_altered"] == 3
    assert candidate["median_os_wt"] == 30
    assert candidate["delta_os_months"] == -27
    assert candidate["altered_events"] == candidate["altered_censored"] == 10
    assert candidate["unaltered_events"] == candidate["unaltered_censored"] == 10
    curve = next(curve for curve in report["survival_curves"] if curve["association"]["biomarker"] == "DURATION")
    assert curve["altered"]["timeline"] == [0, 1, 2, 3, 4]
    assert curve["altered"]["survival_probability"] == pytest.approx([1, .75, .75, .375, .375])
    assert curve["altered"]["at_risk"] == [20, 20, 15, 10, 5]
    oracle_km = KaplanMeierFitter(alpha=.05).fit(altered, event_observed=events)
    assert curve["altered"]["ci_lower"] == pytest.approx(oracle_km.confidence_interval_.iloc[:, 0].to_list())
    for info in report["inputs"].values():
        assert info["sha256"] == hashlib.sha256(Path(info["path"]).read_bytes()).hexdigest()
    exported = list(csv.DictReader(io.StringIO(export_tests_csv(report["tests"]))))
    assert len(exported) == 2
    assert "logrank_statistic" in exported[0]
    assert "fisher_p_value" not in exported[0]
    for text in ("Kaplan-Meier", "Benjamini–Hochberg", "FDR (q ≤ 0.05)", "95% confidence", "Right-censoring is accounted for", "top-12"):
        assert text in report["summary"]


@pytest.mark.parametrize("p_value,selected", [(0.05, True), (np.nextafter(0.05, 1.0), False), (float("nan"), False)])
def test_primary_significance_boundary(
    cohort: Path, monkeypatch: pytest.MonkeyPatch, p_value: float, selected: bool,
) -> None:
    monkeypatch.setattr("co_scientist.analysis.logrank_test", lambda *args, **kwargs: SimpleNamespace(test_statistic=3.84, p_value=p_value))
    report = profile_dataset(cohort, target_drugs=["DRUG_A"])
    assert bool(report["candidates"]) is selected
    assert all(test["nominally_significant"] is selected for test in report["tests"])
    json.dumps(report, allow_nan=False)


def test_censoring_changes_analysis_and_unreached_medians_are_null(cohort: Path) -> None:
    rows = list(csv.DictReader((cohort / "clinical.csv").read_text().splitlines()))
    for row in rows:
        row["event"] = "0"
    with (cohort / "clinical.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    report = profile_dataset(cohort, target_drugs=["DRUG_A"])
    assert report["candidates"] == []
    assert report["survival_curves"] == []
    assert all(test["p_value"] == 1 for test in report["tests"])
    assert all(test["median_os_altered"] is None and test["median_os_wt"] is None and test["delta_os_months"] is None for test in report["tests"])
    assert "No significant, eligible associations" in report["summary"]
    json.dumps(report, allow_nan=False)


def test_significant_count_and_top_three_distinct_biomarkers(cohort: Path) -> None:
    for name in ("mutations.csv", "deletions.csv"):
        with (cohort / name).open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["sample_id", *(f"GENE_{i}" for i in range(15))])
            for i in range(40):
                writer.writerow([f"S{i}", *([int(i < 20)] * 15)])
    report = profile_dataset(cohort, target_drugs=["DRUG_A"])
    assert report["selection"]["nominally_significant_tests"] == 30
    assert len(report["candidates"]) == 12
    assert len({candidate["biomarker"] for candidate in report["candidates"]}) == 12
    assert len(report["survival_curves"]) == 3
    assert len({curve["association"]["biomarker"] for curve in report["survival_curves"]}) == 3
    images = survival_plot_images(report)
    assert len(images) == 3
    for path, body in images.items():
        assert f"]({path})" in report["summary"]
        picture = Image.open(io.BytesIO(body))
        assert picture.format == "PNG"
        assert picture.width >= 1000 and picture.height >= 800


def test_invalid_survival_records_and_matrix_values_are_excluded(cohort: Path) -> None:
    with (cohort / "clinical.csv").open("a") as f:
        f.write("MISSING,DRUG_A,,1\nNEGATIVE,DRUG_A,-2,1\nUNKNOWN,DRUG_A,3,unknown\nNAN,DRUG_A,nan,1\n")
    with (cohort / "mutations.csv").open("a") as f:
        f.write("S0,1,1,1\n")  # Repeated sample must not inflate group counts.
    with (cohort / "mutations.csv").open(newline="") as f:
        matrix_rows = list(csv.reader(f))
    matrix_rows[2][1] = ""  # A missing alteration must not become unaltered.
    with (cohort / "mutations.csv").open("w", newline="") as f:
        csv.writer(f).writerows(matrix_rows)
    report = profile_dataset(cohort, target_drugs=["DRUG_A"])
    assert report["sample_count"] == 40
    assert report["data_handling"]["metadata"]["invalid_duration_rows"] == 3
    assert report["data_handling"]["metadata"]["unknown_event_rows"] == 1
    assert report["data_handling"]["matrix_screens"]["mutation/DRUG_A"]["duplicate_rows_excluded"] == 1
    assert report["data_handling"]["matrix_screens"]["mutation/DRUG_A"]["invalid_alteration_cells_excluded"] == 1
    assert {test["biomarker"]: test["sample_size"] for test in report["tests"]} == {"DURATION": 39, "EVENT_ONLY": 40}


def test_duration_requires_matching_event_column(cohort: Path) -> None:
    (cohort / "clinical.csv").write_text("sample_id,drug,OS_MONTHS,PFS_STATUS\nS1,DRUG_A,3,1\n")
    with pytest.raises(ValueError, match="matching event/censoring"):
        profile_dataset(cohort)


def test_validator_does_not_hide_tiny_p_value_changes(cohort: Path) -> None:
    report = profile_dataset(cohort, target_drugs=["DRUG_A"])
    reference = _reference(report)
    report["candidates"][0]["p_value"] = 1e-100
    reference["candidates"][0]["p_value"] = 2e-100
    validation = compare_reference(report, reference)
    assert not validation["all_matched"]
    assert any(diff["field"].endswith("/p_value") for diff in validation["differences"])


def test_validator_identifies_changed_method(cohort: Path) -> None:
    report = profile_dataset(cohort, target_drugs=["DRUG_A"])
    reference = _reference(report)
    reference["methods"]["primary_test"] = "scipy.stats.mannwhitneyu"
    validation = compare_reference(report, reference)
    assert validation["method_changed"]
    assert not validation["all_matched"]


def test_standalone_validator_exit_status_and_plot_artifacts(cohort: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sqlite3.connect", lambda *args, **kwargs: pytest.fail("Standalone statistics opened SQLite"))
    report = profile_dataset(cohort, target_drugs=["DRUG_A"])
    reference = _reference(report)
    reference_path = cohort / "reference.json"
    reference_path.write_text(json.dumps(reference))
    output = cohort / "validation"
    args = ["--data-dir", str(cohort), "--reference", str(reference_path), "--output-dir", str(output)]
    assert main(args) == 0
    assert json.loads((output / "validation.json").read_text())["all_matched"]
    summary = (output / "summary.md").read_text()
    for curve in report["survival_curves"]:
        assert (output / curve["path"]).read_bytes().startswith(b"\x89PNG")
        assert f"]({curve['path']})" in summary
    assert not (cohort / "co_scientist.db").exists()
    reference["candidates"][0]["p_value"] *= 2
    reference_path.write_text(json.dumps(reference))
    assert main(args) == 1
    assert json.loads(reference_path.read_text())["candidates"][0]["p_value"] == reference["candidates"][0]["p_value"]


def test_unknown_treatment_is_an_error(cohort: Path) -> None:
    with pytest.raises(ValueError, match="Treatments not found"):
        profile_dataset(cohort, target_drugs=["NOT_A_DRUG"])


def test_profile_returns_points_for_significant_candidates_only(cohort: Path) -> None:
    report = profile_dataset(cohort, target_drugs=["DRUG_A"])
    candidates = report["candidates"]
    assert {c["biomarker"] for c in candidates} == {"DURATION", "EVENT_ONLY"}
    candidate = next(c for c in candidates if c["biomarker"] == "DURATION")
    assert candidate["candidate_key"] == "DURATION|mutation|DRUG_A"
    assert all("points" not in c for c in candidates)
    # UNDERPOWERED is never tested, so it has no points either.
    assert set(report["points"]) == {c["candidate_key"] for c in candidates}
    assert "UNDERPOWERED|mutation|DRUG_A" not in report["points"]
    points = report["points"][candidate["candidate_key"]]
    assert {p["group"] for p in points} == {"altered", "unaltered"}
    assert sum(p["group"] == "altered" for p in points) == candidate["altered_samples"]
    assert sum(p["group"] == "unaltered" for p in points) == candidate["unaltered_samples"]
    assert {p["sample_id"]: p["value"] for p in points}["S0"] == 1
    assert all(set(p) == {"sample_id", "group", "value", "event"} for p in points)
    assert {p["event"] for p in points} <= {0, 1}
    assert sum(p["event"] for p in points if p["group"] == "altered") == candidate["altered_events"]


def test_reported_candidates_carry_a_cox_hazard_ratio(cohort: Path) -> None:
    report = profile_dataset(cohort, target_drugs=["DRUG_A"])
    for c in report["candidates"]:
        assert {"hazard_ratio", "hr_ci_lower", "hr_ci_upper"} <= set(c)
        if c["hazard_ratio"] is not None:
            assert c["hr_ci_lower"] <= c["hazard_ratio"] <= c["hr_ci_upper"]
    # The fixture's arms never overlap in time, so no finite hazard ratio exists.
    duration = next(c for c in report["candidates"] if c["biomarker"] == "DURATION")
    assert duration["hazard_ratio"] is None


def test_hazard_ratio_on_overlapping_groups() -> None:
    from co_scientist.analysis import _hazard_ratio

    # Altered samples die at half the unaltered times, with overlap and censoring.
    points = [
        {"sample_id": f"A{i}", "group": "altered", "value": float(1 + i), "event": int(i % 3 != 0)}
        for i in range(20)
    ] + [
        {"sample_id": f"U{i}", "group": "unaltered", "value": float(2 + 2 * i),
         "event": int(i % 3 != 0)}
        for i in range(20)
    ]
    hr = _hazard_ratio(points)
    assert hr["hazard_ratio"] is not None and hr["hazard_ratio"] > 1
    assert hr["hr_ci_lower"] < hr["hazard_ratio"] < hr["hr_ci_upper"]


def test_hazard_ratio_is_null_without_event_flags() -> None:
    from co_scientist.analysis import _hazard_ratio

    legacy = [{"sample_id": f"S{i}", "group": "altered" if i < 15 else "unaltered",
               "value": float(i + 1)} for i in range(30)]
    assert _hazard_ratio(legacy) == {
        "hazard_ratio": None, "hr_ci_lower": None, "hr_ci_upper": None,
    }


def test_points_memory_bounded_by_reported_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from co_scientist import analysis
    from co_scientist.analysis import DatasetProfiler

    with (tmp_path / "clinical.csv").open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["sample_id", "drug", "os_months", "event"])
        for i in range(40):
            writer.writerow([f"S{i}", "DRUG_A", (i % 4 + 1) * (1 if i < 20 else 10), i % 2 == 0])
    with (tmp_path / "mutations.csv").open("w", newline="") as f:
        writer = csv.writer(f)
        genes = [f"G{j}" for j in range(30)]
        writer.writerow(["sample_id", *genes])
        for i in range(40):  # every gene separates the arms, so all 30 are significant
            writer.writerow([f"S{i}", *[int(i < 20 if j % 2 else i < 21) for j in range(30)]])
    expected = profile_dataset(tmp_path, target_drugs=["DRUG_A"])
    monkeypatch.setattr(analysis, "MAX_CANDIDATES", 3)
    profiler = DatasetProfiler()
    report = profiler.profile(tmp_path, target_drugs=["DRUG_A"])
    assert report["selection"]["nominally_significant_tests"] >= 20
    assert len(report["candidates"]) == 3
    assert profiler.peak_points <= 4  # the limit, plus the one being offered
    assert len(profiler.points) <= 3
    assert set(report["points"]) == {c["candidate_key"] for c in report["candidates"]}
    assert [c["candidate_key"] for c in report["candidates"]] == [
        c["candidate_key"] for c in expected["candidates"][:3]
    ]
