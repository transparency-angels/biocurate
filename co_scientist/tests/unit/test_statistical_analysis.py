"""Validate the scientific calculations independently of agent orchestration."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path

import numpy as np
import pytest
from scipy import stats

from co_scientist.analysis import profile_dataset
from co_scientist.analysis import tests_csv as export_tests_csv
from scripts.validate_data_analysis import compare_reference, main


@pytest.fixture
def cohort(tmp_path: Path) -> Path:
    with (tmp_path / "clinical.csv").open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["sample_id", "drug", "os_months", "event"])
        for i in range(40):
            # Equal event rates in the strong-duration groups, but a strong
            # event association with EVENT_ONLY and identical durations there.
            writer.writerow([f"S{i}", "DRUG_A", (10 if i < 20 else 40) + i % 5, int(i % 2 == 0)])
    with (tmp_path / "mutations.csv").open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["sample_id", "DURATION", "EVENT_ONLY", "UNDERPOWERED"])
        for i in range(40):
            writer.writerow([f"S{i}", int(i < 20), int(i % 2 == 0), int(i < 9)])
    return tmp_path


def test_statistics_match_independent_vectors_and_tables(cohort: Path) -> None:
    report = profile_dataset(cohort, target_drugs=["DRUG_A"])
    assert report["sample_count"] == 40
    assert report["selection"]["eligible_tests"] == 2
    assert report["selection"]["nominally_significant_tests"] == 1
    assert [c["biomarker"] for c in report["candidates"]] == ["DURATION"]
    candidate = report["candidates"][0]
    # Oracle vectors are built directly, without calling any loading helpers.
    altered = [10 + i % 5 for i in range(20)]
    unaltered = [40 + i % 5 for i in range(20)]
    expected_u, expected_p = stats.mannwhitneyu(altered, unaltered, alternative="two-sided")
    expected_or, expected_fisher = stats.fisher_exact([[10, 10], [10, 10]])
    assert candidate["u_statistic"] == expected_u
    assert candidate["p_value"] == pytest.approx(expected_p, rel=1e-12, abs=0)
    assert candidate["delta_os_months"] == -30
    assert candidate["odds_ratio"] == expected_or
    assert candidate["fisher_p_value"] == expected_fisher == 1.0
    assert [candidate[k] for k in ("altered_events", "altered_no_event", "unaltered_events", "unaltered_no_event")] == [10, 10, 10, 10]

    event_only = next(test for test in report["tests"] if test["biomarker"] == "EVENT_ONLY")
    assert event_only["p_value"] == 1.0
    assert event_only["fisher_p_value"] < 0.05
    assert not event_only["nominally_significant"]
    assert event_only["odds_ratio"] is None  # Infinite odds must not become 1.
    assert event_only["odds_ratio_nonfinite"]
    exported = list(csv.DictReader(io.StringIO(export_tests_csv(report["tests"]))))
    assert len(exported) == 2
    assert {row["nominally_significant"] for row in exported} == {"True", "False"}
    for info in report["inputs"].values():
        assert info["sha256"] == hashlib.sha256(Path(info["path"]).read_bytes()).hexdigest()
    summary = report["summary"]
    for text in ("Mann-Whitney U", "p-value ≤ 0.05", "Fisher", "No multiple-testing correction", "Censoring is not accounted for", "top-12"):
        assert text in summary


@pytest.mark.parametrize("p_value,selected", [(0.05, True), (np.nextafter(0.05, 1.0), False), (float("nan"), False)])
def test_primary_significance_boundary(
    cohort: Path, monkeypatch: pytest.MonkeyPatch, p_value: float, selected: bool,
) -> None:
    monkeypatch.setattr("co_scientist.analysis.stats.mannwhitneyu", lambda *args, **kwargs: (100.0, p_value))
    report = profile_dataset(cohort, target_drugs=["DRUG_A"])
    assert bool(report["candidates"]) is selected
    assert all(test["nominally_significant"] is selected for test in report["tests"])


def test_significant_count_is_not_top_twelve_count(cohort: Path) -> None:
    for name in ("mutations.csv", "deletions.csv"):
        with (cohort / name).open("w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["sample_id", *(f"GENE_{i}" for i in range(15))])
            for i in range(40):
                writer.writerow([f"S{i}", *([int(i < 20)] * 15)])
    report = profile_dataset(cohort, target_drugs=["DRUG_A"])
    assert report["selection"]["nominally_significant_tests"] == 30
    assert len(report["candidates"]) == 12
    assert len({c["biomarker"] for c in report["candidates"]}) == 12
    assert "comparisons (unadjusted p ≤ 0.05): **30**" in report["summary"]


def test_validator_does_not_hide_tiny_p_value_changes(cohort: Path) -> None:
    report = profile_dataset(cohort, target_drugs=["DRUG_A"])
    reference = {key: report[key] for key in ("sample_count", "drugs", "candidates")}
    reference = json.loads(json.dumps(reference))
    report["candidates"][0]["p_value"] = 1e-100
    reference["candidates"][0]["p_value"] = 2e-100
    validation = compare_reference(report, reference)
    assert not validation["all_matched"]
    assert any(diff["field"].endswith("/p_value") for diff in validation["differences"])


def test_standalone_validator_exit_status_and_artifacts(cohort: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sqlite3.connect", lambda *args, **kwargs: pytest.fail("Standalone statistics opened SQLite"))
    report = profile_dataset(cohort, target_drugs=["DRUG_A"])
    reference = {key: report[key] for key in ("sample_count", "drugs", "candidates")}
    reference_path = cohort / "reference.json"
    reference_path.write_text(json.dumps(reference))
    output = cohort / "validation"
    args = ["--data-dir", str(cohort), "--reference", str(reference_path), "--output-dir", str(output)]
    assert main(args) == 0
    assert json.loads((output / "validation.json").read_text())["all_matched"]
    assert (output / "summary.md").is_file()
    assert (output / "statistical_tests.csv").is_file()
    assert (output / "biomarker_candidates.json").is_file()
    assert not (cohort / "co_scientist.db").exists()
    reference["candidates"][0]["p_value"] *= 2
    reference_path.write_text(json.dumps(reference))
    assert main(args) == 1
    assert not json.loads((output / "validation.json").read_text())["all_matched"]
    # The reference is preserved, rather than overwritten by the new report.
    assert json.loads(reference_path.read_text())["candidates"][0]["p_value"] == reference["candidates"][0]["p_value"]


def test_unknown_treatment_is_an_error(cohort: Path) -> None:
    with pytest.raises(ValueError, match="Treatments not found"):
        profile_dataset(cohort, target_drugs=["NOT_A_DRUG"])
