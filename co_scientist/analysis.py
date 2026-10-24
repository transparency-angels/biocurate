"""Kaplan-Meier biomarker profiling from flat tables, independent of sessions."""

from __future__ import annotations

import csv
import hashlib
import io
import platform
from collections import defaultdict
from datetime import UTC, datetime
from fnmatch import fnmatchcase
from importlib.metadata import version
from pathlib import Path
from typing import Any

import lifelines
import numpy as np
from lifelines import KaplanMeierFitter
from lifelines.statistics import logrank_test

from .storage.datasets import TABULAR_SUFFIXES, table_delimiter, tabular_files

SAMPLE_ID_COLUMNS = ("SAMPLE_ID", "PATIENT_ID", "SAMPLE", "ID")
DRUG_COLUMNS = ("DRUG", "TREATMENT")
ENDPOINTS = (
    ("OS_MONTHS", ("OS_STATUS", "VITAL_STATUS", "STATUS", "EVENT"), "Overall survival"),
    ("PFS_MONTHS", ("PFS_STATUS", "STATUS", "EVENT"), "Progression-free survival"),
    ("SURVIVAL_MONTHS", ("STATUS", "EVENT", "VITAL_STATUS", "OS_STATUS"), "Survival"),
    ("TIME", ("STATUS", "EVENT", "VITAL_STATUS", "OS_STATUS", "PFS_STATUS"), "Survival"),
)
SURVIVAL_COLUMNS = tuple(endpoint[0] for endpoint in ENDPOINTS)
STATUS_COLUMNS = tuple(dict.fromkeys(column for _, columns, _ in ENDPOINTS for column in columns))
ALPHA = 0.05
MIN_COHORT = 20
MIN_GROUP = 10
MAX_CANDIDATES = 12
MAX_CURVES = 3


class DatasetNotFoundError(ValueError):
    """No table with a compatible clinical metadata header was found."""


def _event_flag(value: str) -> int | None:
    code = value.strip().upper().split(":", 1)[0]
    if code in {"1", "1.0", "TRUE", "YES", "DECEASED", "DEAD", "DEATH", "EVENT", "PROGRESSION", "PROGRESSED"}:
        return 1
    if code in {"0", "0.0", "FALSE", "NO", "LIVING", "ALIVE", "CENSORED", "NO EVENT", "NO_EVENT"}:
        return 0
    return None


def _finite_median(fitter: KaplanMeierFitter) -> float | None:
    median = float(fitter.median_survival_time_)
    return round(median, 2) if np.isfinite(median) else None


def _curve_data(fitter: KaplanMeierFitter) -> dict[str, Any]:
    """Persist aggregate curve estimates, rather than individual observations."""
    table = fitter.event_table
    return {
        "timeline": fitter.survival_function_.index.to_list(),
        "survival_probability": fitter.survival_function_.iloc[:, 0].to_list(),
        "ci_lower": fitter.confidence_interval_.iloc[:, 0].to_list(),
        "ci_upper": fitter.confidence_interval_.iloc[:, 1].to_list(),
        "censored": table["censored"].astype(int).to_list(),
        "removed": table["removed"].astype(int).to_list(),
        "at_risk": table["at_risk"].astype(int).to_list(),
    }


class DatasetProfiler:
    """Estimate survival and collect every eligible log-rank comparison."""

    def __init__(self) -> None:
        self.tests: list[dict[str, Any]] = []
        self.matrix_paths: dict[str, Path] = {}
        self.top_curves: dict[str, dict[str, Any]] = {}
        self.data_handling: dict[str, Any] = {}
        self.endpoint: dict[str, str] = {}
        self.points: dict[str, list[dict[str, Any]]] = {}

    def profile(
        self, data_dir: Path, *, goal: str = "", target_drugs: list[str] | None = None,
    ) -> dict[str, Any]:
        data_dir = data_dir.expanduser().resolve()
        if not data_dir.is_dir():
            raise NotADirectoryError(f"Dataset directory does not exist or is not a directory: {data_dir}")
        self.tests = []
        self.matrix_paths = {}
        self.top_curves = {}
        self.points = {}
        self.data_handling = {"matrix_screens": {}}
        metadata_path = self._find_metadata_file(data_dir)
        if metadata_path is None:
            raise DatasetNotFoundError(
                f"No clinical metadata table found in {data_dir}. Expected a CSV, TSV, or "
                "tab-delimited TXT file with a sample ID and treatment or survival columns."
            )
        samples, drugs = self._load_patient_metadata(metadata_path)
        if target_drugs is None:
            selected_drugs = self._select_target_drugs(goal, drugs)
        else:
            selected_drugs = list(dict.fromkeys(drug.strip().upper() for drug in target_drugs))
            unknown = [drug for drug in selected_drugs if drug not in drugs]
            if unknown:
                raise ValueError(f"Treatments not found in eligible metadata: {', '.join(unknown)}")
        candidates = self._screen_alterations(data_dir, samples, selected_drugs)
        inputs = {}
        for role, path in {"metadata": metadata_path, **self.matrix_paths}.items():
            with path.open("rb") as f:
                digest = hashlib.file_digest(f, "sha256").hexdigest()
            inputs[role] = {"path": str(path), "sha256": digest, "bytes": path.stat().st_size}
        curves = sorted(self.top_curves.values(), key=lambda curve: curve["association"]["p_value"])
        for rank, curve in enumerate(curves, 1):
            curve["path"] = f"plots/kaplan_meier_{rank}.png"
        report = {
            "candidates": candidates,
            "points": {c["candidate_key"]: self.points[c["candidate_key"]] for c in candidates},
            "drugs": selected_drugs,
            "sample_count": len(samples),
            "generated_at": datetime.now(UTC).isoformat(),
            "inputs": inputs,
            "endpoint": self.endpoint,
            "data_handling": self.data_handling,
            "survival_curves": curves,
            "software": {"python": platform.python_version(), "numpy": np.__version__, "lifelines": lifelines.__version__, "matplotlib": version("matplotlib")},
            "methods": {
                "survival_estimator": "lifelines.KaplanMeierFitter",
                "primary_test": "lifelines.statistics.logrank_test",
                "test_distribution": "chi-squared, 1 degree of freedom",
                "weightings": None,
                "alpha": ALPHA,
                "confidence_level": 1 - ALPHA,
                "significance_rule": "finite p_value <= alpha",
                "multiple_testing_correction": "none",
                "min_treatment_samples": MIN_COHORT,
                "min_altered_samples": MIN_GROUP,
                "min_unaltered_samples": MIN_GROUP,
                "censoring_adjustment": "right-censored; event_observed=1 for event, 0 for censoring",
                "effect_size": "difference in Kaplan-Meier median survival; null when either median is not reached",
            },
            "selection": {
                "eligible_tests": len(self.tests),
                "nominally_significant_tests": sum(test["nominally_significant"] for test in self.tests),
                "reported_candidates": len(candidates),
                "candidate_limit": MAX_CANDIDATES,
                "rule": "Sort by log-rank p-value; keep the strongest alteration per gene/treatment; take the first 12.",
                "drug_selection": "explicit" if target_drugs is not None else "goal mentions or largest eligible metadata row counts",
                "plot_selection": "Strongest significant treatment/alteration association for each of the top 3 distinct genes.",
            },
        }
        report["summary"] = render_summary(report)
        report["tests"] = self.tests
        return report

    def _find_metadata_file(self, data_dir: Path) -> Path | None:
        preferred = ["patient_metadata", "metadata", "pfs_months", "os_time_adjusted"]
        paths = sorted(
            tabular_files(data_dir),
            key=lambda p: preferred.index(p.stem.lower()) if p.stem.lower() in preferred else len(preferred),
        )
        for path in paths:
            with path.open(encoding="utf-8-sig", newline="") as f:
                header = next(csv.reader(f, delimiter=table_delimiter(path)), [])
            columns = {column.strip().upper() for column in header}
            if columns.intersection(SAMPLE_ID_COLUMNS) and columns.intersection(
                DRUG_COLUMNS + SURVIVAL_COLUMNS + STATUS_COLUMNS
            ):
                return path
        return None

    def _load_patient_metadata(self, metadata_path: Path) -> tuple[dict[str, dict[str, Any]], dict[str, list[str]]]:
        samples: dict[str, dict[str, Any]] = {}
        drugs: dict[str, list[str]] = defaultdict(list)
        audit = dict.fromkeys(("rows", "missing_id_rows", "invalid_duration_rows", "unknown_event_rows", "duplicate_valid_rows"), 0)
        with metadata_path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f, delimiter=table_delimiter(metadata_path))
            columns = {column.strip().upper() for column in reader.fieldnames or []}
            # Select one endpoint for the table. OS duration never inherits a
            # PFS event flag, and missing rows never switch to another endpoint.
            for duration_column, status_columns, label in ENDPOINTS:
                event_column = next((column for column in status_columns if column in columns), None)
                if duration_column in columns and event_column is not None:
                    self.endpoint = {"duration_column": duration_column, "event_column": event_column, "label": label, "unit": "months"}
                    break
            else:
                raise ValueError("Kaplan-Meier analysis requires a duration column and a matching event/censoring column.")
            for row in reader:
                audit["rows"] += 1
                row = {key.strip().upper(): (value or "").strip() for key, value in row.items() if key is not None}
                sid = next((row[key] for key in SAMPLE_ID_COLUMNS if row.get(key)), "")
                if not sid:
                    audit["missing_id_rows"] += 1
                    continue
                try:
                    duration = float(row[self.endpoint["duration_column"]])
                except (ValueError, KeyError):
                    duration = float("nan")
                if not np.isfinite(duration) or duration < 0:
                    audit["invalid_duration_rows"] += 1
                    continue
                event = _event_flag(row.get(self.endpoint["event_column"], ""))
                if event is None:
                    audit["unknown_event_rows"] += 1
                    continue
                if sid in samples:
                    audit["duplicate_valid_rows"] += 1
                else:
                    samples[sid] = {"os_months": duration, "status": event, "drugs": set()}
                drug = next((row[key] for key in DRUG_COLUMNS if row.get(key)), "").upper()
                if drug:
                    samples[sid]["drugs"].add(drug)
                    drugs[drug].append(sid)
        audit["eligible_samples"] = len(samples)
        self.data_handling["metadata"] = audit
        return samples, drugs

    def _select_target_drugs(self, goal: str, available_drugs: dict[str, list[str]]) -> list[str]:
        mentioned = [drug for drug in available_drugs if drug in goal.upper() and len(available_drugs[drug]) >= 10]
        if mentioned:
            return sorted(mentioned, key=lambda drug: len(available_drugs[drug]), reverse=True)[:3]
        sorted_drugs = sorted(available_drugs.items(), key=lambda item: len(item[1]), reverse=True)
        return [drug for drug, sids in sorted_drugs[:4] if len(sids) >= 30]

    def _screen_alterations(
        self, data_dir: Path, samples: dict[str, dict[str, Any]], target_drugs: list[str],
    ) -> list[dict[str, Any]]:
        specs = [
            ("mutation", ["cell2mutation_labeled", "*mutation*", "*mut*"]),
            ("amplification", ["cell2cnamplification_labeled", "*amplification*"]),
            ("deletion", ["cell2cndeletion_labeled", "*deletion*"]),
        ]
        candidates = []
        for alteration, stems in specs:
            path = self._find_matrix_file(data_dir, [f"{stem}{suffix}" for stem in stems for suffix in TABULAR_SUFFIXES])
            if path is None:
                continue
            self.matrix_paths[alteration] = path
            for drug in target_drugs:
                candidates.extend(self._screen_single_matrix(path, alteration, drug, samples))
        candidates.sort(key=lambda candidate: candidate["p_value"])
        seen = set()
        unique = []
        for candidate in candidates:
            key = (candidate["biomarker"], candidate["drug"])
            if key not in seen:
                seen.add(key)
                unique.append(candidate)
        return unique[:MAX_CANDIDATES]

    def _find_matrix_file(self, data_dir: Path, patterns: list[str]) -> Path | None:
        paths = tabular_files(data_dir)
        return next((path for pattern in patterns for path in paths if fnmatchcase(path.name.lower(), pattern.lower())), None)

    def _screen_single_matrix(
        self, matrix_path: Path, alteration: str, drug: str, samples: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        target = {sid: sample for sid, sample in samples.items() if drug in sample["drugs"]}
        if len(target) < MIN_COHORT:
            return []
        audit = {"matched_samples": 0, "duplicate_rows_excluded": 0, "invalid_alteration_cells_excluded": 0}
        self.data_handling["matrix_screens"][f"{alteration}/{drug}"] = audit
        with matrix_path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f, delimiter=table_delimiter(matrix_path))
            header = next(reader, [])
            if len(header) < 2:
                return []
            genes = [column.strip() for column in header[1:]]
            durations = [[[], []] for _ in genes]
            events = [[[], []] for _ in genes]
            sample_ids = [[[], []] for _ in genes]
            seen = set()
            for row in reader:
                if not row or row[0].strip() not in target:
                    continue
                sid = row[0].strip()
                if sid in seen:
                    audit["duplicate_rows_excluded"] += 1
                    continue
                seen.add(sid)
                audit["matched_samples"] += 1
                sample = target[sid]
                for i in range(len(genes)):
                    value = row[i + 1].strip().lower() if i + 1 < len(row) else ""
                    if value in {"1", "1.0", "true"}:
                        group = 0
                    elif value in {"0", "0.0", "false"}:
                        group = 1
                    else:
                        audit["invalid_alteration_cells_excluded"] += 1
                        continue
                    durations[i][group].append(sample["os_months"])
                    events[i][group].append(sample["status"])
                    sample_ids[i][group].append(sid)
        candidates = []
        for gene, (altered_t, unaltered_t), (altered_e, unaltered_e), (
            altered_s, unaltered_s,
        ) in zip(genes, durations, events, sample_ids, strict=True):
            if not gene or min(len(altered_t), len(unaltered_t)) < MIN_GROUP:
                continue
            result = logrank_test(altered_t, unaltered_t, event_observed_A=altered_e, event_observed_B=unaltered_e)
            altered_km = KaplanMeierFitter(alpha=ALPHA).fit(altered_t, event_observed=altered_e, label="Altered")
            unaltered_km = KaplanMeierFitter(alpha=ALPHA).fit(unaltered_t, event_observed=unaltered_e, label="Unaltered")
            median_alt = _finite_median(altered_km)
            median_wt = _finite_median(unaltered_km)
            delta = round(median_alt - median_wt, 2) if median_alt is not None and median_wt is not None else None
            relationship = "survival_association_direction_undetermined"
            if delta is not None and delta != 0:
                relationship = "reduced_response_or_poor_prognosis" if delta < 0 else "favorable_response_or_prognosis"
            p_value = float(result.p_value)
            test = {
                "biomarker": gene, "alteration_type": alteration, "drug": drug,
                "relationship": relationship, "delta_os_months": delta,
                "median_os_altered": median_alt, "median_os_wt": median_wt,
                "p_value": p_value if np.isfinite(p_value) else None,
                "logrank_statistic": float(result.test_statistic),
                "test_method": "lifelines.statistics.logrank_test",
                "survival_estimator": "lifelines.KaplanMeierFitter",
                "sample_size": len(altered_t) + len(unaltered_t),
                "altered_samples": len(altered_t), "unaltered_samples": len(unaltered_t),
                "altered_events": sum(altered_e), "unaltered_events": sum(unaltered_e),
                "altered_censored": len(altered_e) - sum(altered_e),
                "unaltered_censored": len(unaltered_e) - sum(unaltered_e),
                "nominally_significant": bool(np.isfinite(p_value) and p_value <= ALPHA),
                "matrix_file": str(matrix_path), "cohort": f"Clinical cohort ({drug})",
                "candidate_key": f"{gene}|{alteration}|{drug}",
            }
            self.tests.append(test)
            if test["nominally_significant"]:
                candidates.append(test)
                self.points[test["candidate_key"]] = [
                    {"sample_id": sid, "group": name, "value": value}
                    for name, ids, values in (
                        ("altered", altered_s, altered_t), ("unaltered", unaltered_s, unaltered_t),
                    )
                    for sid, value in zip(ids, values, strict=True)
                ]
                existing = self.top_curves.get(gene)
                if existing is None or p_value < existing["association"]["p_value"]:
                    self.top_curves[gene] = {"association": test, "altered": _curve_data(altered_km), "unaltered": _curve_data(unaltered_km)}
                    if len(self.top_curves) > MAX_CURVES:
                        worst = max(self.top_curves, key=lambda name: self.top_curves[name]["association"]["p_value"])
                        del self.top_curves[worst]
        return candidates


def profile_dataset(data_dir: Path, *, goal: str = "", target_drugs: list[str] | None = None) -> dict[str, Any]:
    """Run survival profiling without a database, session, or LLM."""
    return DatasetProfiler().profile(data_dir, goal=goal, target_drugs=target_drugs)


def tests_csv(tests: list[dict[str, Any]]) -> str:
    columns = [
        "biomarker", "alteration_type", "drug", "test_method", "survival_estimator",
        "sample_size", "altered_samples", "unaltered_samples", "logrank_statistic", "p_value",
        "nominally_significant", "median_os_altered", "median_os_wt", "delta_os_months",
        "altered_events", "altered_censored", "unaltered_events", "unaltered_censored", "relationship", "matrix_file",
    ]
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(tests)
    return output.getvalue()


def _median_text(value: float | None) -> str:
    return "NR" if value is None else f"{value:.2f}"


def render_summary(report: dict[str, Any]) -> str:
    """Keep report sections while explaining survival estimates and comparisons."""
    endpoint = report["endpoint"]
    metadata = report["data_handling"]["metadata"]
    parts = [
        "# Dataset & Biomarker Profiling Summary", "",
        f"- Unique eligible sample IDs loaded from clinical metadata: **{report['sample_count']}**",
        f"- Targeted treatment arms screened: **{', '.join(report['drugs'])}**",
        f"- Endpoint: **{endpoint['label']}** (`{endpoint['duration_column']}`, `{endpoint['event_column']}`; months).",
        f"- Gene/alteration/treatment comparisons tested: **{report['selection']['eligible_tests']}**",
        f"- Nominally significant comparisons (unadjusted log-rank p ≤ {ALPHA}): **{report['selection']['nominally_significant_tests']}**",
        f"- Candidate associations reported after deduplication and the top-{MAX_CANDIDATES} limit: **{len(report['candidates'])}**",
        "", "## Statistical methods and significance", "",
        "- Survival estimator: **Kaplan-Meier**, using `lifelines.KaplanMeierFitter` separately for altered and unaltered samples. "
        "Observed events use `event_observed=1`; right-censored observations use `event_observed=0`.",
        "- Primary comparison: **unweighted two-group log-rank test**, using `lifelines.statistics.logrank_test`. "
        "The null hypothesis is equal hazards/survival functions across groups. The statistic is compared with a chi-squared distribution with 1 degree of freedom. "
        "Kaplan-Meier is the estimator; log-rank supplies the comparison p-value.",
        f"- **Statistical significance means a finite, unadjusted log-rank p-value ≤ {ALPHA}.** "
        "No multiple-testing correction or false discovery rate control is applied; these remain nominal, exploratory associations.",
        f"- Eligibility: at least {MIN_COHORT} valid metadata samples exposed to a treatment and at least {MIN_GROUP} altered and {MIN_GROUP} unaltered matched observations per gene.",
        "- Effects are **Kaplan-Meier median survival** and altered minus unaltered KM medians, rounded to two decimals. "
        "`NR` means the estimated survival curve did not reach 0.5; its median and any difference involving it are null in the data exports. "
        "No finite effect or direction is invented when a median is not reached.",
        "- Curves show **95% confidence intervals**, using lifelines' Greenwood log-log intervals. Plus signs mark censoring, and the tables show numbers at risk just before each time point.",
        f"- Reporting: sort by log-rank p-value, retain the strongest alteration per gene/treatment, and show at most {MAX_CANDIDATES} candidates. "
        f"Plots show the strongest significant association for each of the top {MAX_CURVES} distinct genes.",
        "", "## Data handling and interpretation", "",
        f"- The table uses one endpoint throughout: `{endpoint['duration_column']}` paired with `{endpoint['event_column']}`. "
        "Durations must be finite and nonnegative. Missing/invalid durations and unrecognized event status are excluded rather than imputed.",
        f"- Metadata rows read: **{metadata['rows']}**; excluded for missing ID: **{metadata['missing_id_rows']}**, invalid duration: **{metadata['invalid_duration_rows']}**, "
        f"unknown event status: **{metadata['unknown_event_rows']}**. Duplicate valid metadata rows merged: **{metadata['duplicate_valid_rows']}**.",
        "- The sample ID falls back to patient ID. Repeated IDs retain the first valid duration/status and merge treatment exposures. "
        "Event flags accept 1/0, true/false, deceased/living, and coded statuses such as `1:DECEASED` / `0:LIVING`.",
        "- Matrix values 1/1.0/true mean altered and 0/0.0/false mean unaltered. Other or missing values are excluded per gene; "
        "unmatched IDs and repeated matrix rows are excluded. Exclusion counts per treatment/matrix are in `biomarker_candidates.json`.",
        "- Right-censoring is accounted for. Independent/non-informative censoring is assumed. Log-rank has greatest power under proportional hazards and can miss differences when curves cross. "
        "Treatment arms may overlap; no adjustment is made for clinical covariates or multiple samples from one patient. "
        "Associations alone do not establish treatment-specific benefit or causality.",
        "", "## Top Candidate Biomarkers Associated With Treatment Response", "",
    ]
    if report["candidates"]:
        parts.extend([
            "| Gene | Alteration | Drug | KM median altered / unaltered (months) | Δ KM median months | Log-rank χ² | Log-rank p | Altered / unaltered N | Events altered / unaltered |",
            "| :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ])
        for candidate in report["candidates"]:
            delta = candidate["delta_os_months"]
            effect = "NR" if delta is None else f"{delta:+.2f}"
            parts.append(
                f"| **{candidate['biomarker']}** | {candidate['alteration_type']} | {candidate['drug']} | "
                f"{_median_text(candidate['median_os_altered'])} / {_median_text(candidate['median_os_wt'])} | {effect} | "
                f"{candidate['logrank_statistic']:.4f} | {candidate['p_value']:.4e} | "
                f"{candidate['altered_samples']} / {candidate['unaltered_samples']} | {candidate['altered_events']} / {candidate['unaltered_events']} |"
            )
    else:
        parts.append(f"*(No candidate alterations reached nominal log-rank significance p ≤ {ALPHA}.)*")
    parts.extend(["", "## Kaplan-Meier survival curves for the top 3 biomarkers", ""])
    if not report["survival_curves"]:
        parts.append("No significant, eligible associations were available to plot.")
    for rank, curve in enumerate(report["survival_curves"], 1):
        candidate = curve["association"]
        label = f"{candidate['biomarker']} ({candidate['alteration_type']}) - {candidate['drug']}"
        parts.extend([
            f"### {rank}. {label}", "",
            f"Log-rank p = {candidate['p_value']:.4e}; altered n = {candidate['altered_samples']}, unaltered n = {candidate['unaltered_samples']}. "
            f"KM median survival: {_median_text(candidate['median_os_altered'])} / {_median_text(candidate['median_os_wt'])} months (NR = not reached).", "",
            f"![Kaplan-Meier survival curves for {label}]({curve['path']})", "",
        ])
    software = report["software"]
    parts.extend([
        "## Reproducibility", "",
        f"- Generated at: `{report['generated_at']}` (UTC).",
        f"- Software: Python {software['python']}; NumPy {software['numpy']}; lifelines {software['lifelines']}; matplotlib {software['matplotlib']}.",
        "- Full log-rank comparisons, including nonsignificant results, event/censor counts and KM medians: [statistical_tests.csv](statistical_tests.csv).",
        "- Method parameters, selection/exclusion counts, aggregate KM estimates with confidence intervals, and input hashes: [biomarker_candidates.json](biomarker_candidates.json).",
    ])
    for role, info in report["inputs"].items():
        parts.append(f"- {role}: `{info['path']}` ({info['bytes']} bytes); SHA-256 `{info['sha256']}`.")
    parts.extend([
        "", "Method references: [lifelines KaplanMeierFitter](https://lifelines.readthedocs.io/en/latest/fitters/univariate/KaplanMeierFitter.html), "
        "[lifelines log-rank test](https://lifelines.readthedocs.io/en/latest/lifelines.statistics.html#lifelines.statistics.logrank_test).", "",
    ])
    return "\n".join(parts)
