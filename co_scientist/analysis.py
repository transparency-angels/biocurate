"""Deterministic biomarker profiling from flat tables; no database or LLM required."""

from __future__ import annotations

import csv
import hashlib
import io
import platform
from collections import defaultdict
from datetime import UTC, datetime
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

import numpy as np
import scipy
from scipy import stats

from .logging import get_logger
from .storage.datasets import TABULAR_SUFFIXES, table_delimiter, tabular_files

log = get_logger("data_analysis")

SAMPLE_ID_COLUMNS = ("SAMPLE_ID", "PATIENT_ID", "SAMPLE", "ID")
DRUG_COLUMNS = ("DRUG", "TREATMENT")
SURVIVAL_COLUMNS = ("OS_MONTHS", "PFS_MONTHS", "SURVIVAL_MONTHS", "TIME")
STATUS_COLUMNS = ("OS_STATUS", "PFS_STATUS", "VITAL_STATUS", "STATUS", "EVENT")
ALPHA = 0.05
MIN_COHORT = 20
MIN_GROUP = 10
MAX_CANDIDATES = 12


class DatasetNotFoundError(ValueError):
    """No table with a compatible clinical metadata header was found."""


class DatasetProfiler:
    """Collect every eligible statistical comparison before candidate selection."""

    def __init__(self) -> None:
        self.tests: list[dict[str, Any]] = []
        self.matrix_paths: dict[str, Path] = {}

    def profile(
        self, data_dir: Path, *, goal: str = "", target_drugs: list[str] | None = None,
    ) -> dict[str, Any]:
        data_dir = data_dir.expanduser().resolve()
        if not data_dir.is_dir():
            raise NotADirectoryError(f"Dataset directory does not exist or is not a directory: {data_dir}")
        self.tests = []
        self.matrix_paths = {}
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
                raise ValueError(f"Treatments not found in metadata: {', '.join(unknown)}")
        candidates = self._screen_alterations(data_dir, samples, selected_drugs)
        files = {"metadata": metadata_path, **self.matrix_paths}
        inputs = {}
        for role, path in files.items():
            with path.open("rb") as f:
                digest = hashlib.file_digest(f, "sha256").hexdigest()
            inputs[role] = {"path": str(path), "sha256": digest, "bytes": path.stat().st_size}
        report = {
            "candidates": candidates,
            "drugs": selected_drugs,
            "sample_count": len(samples),
            "generated_at": datetime.now(UTC).isoformat(),
            "inputs": inputs,
            "software": {"python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__},
            "methods": {
                "primary_test": "scipy.stats.mannwhitneyu",
                "alternative": "two-sided",
                "method": "asymptotic",
                "use_continuity": True,
                "alpha": ALPHA,
                "significance_rule": "finite p_value <= alpha",
                "multiple_testing_correction": "none",
                "secondary_test": "scipy.stats.fisher_exact",
                "fisher_alternative": "two-sided",
                "fisher_used_for_selection": False,
                "min_treatment_samples": MIN_COHORT,
                "min_altered_samples": MIN_GROUP,
                "min_unaltered_samples": MIN_GROUP,
                "censoring_adjustment": "none",
            },
            "selection": {
                "eligible_tests": len(self.tests),
                "nominally_significant_tests": sum(test["nominally_significant"] for test in self.tests),
                "reported_candidates": len(candidates),
                "candidate_limit": MAX_CANDIDATES,
                "rule": "Sort by primary p-value; keep the strongest alteration per gene/treatment; take the first 12.",
                "drug_selection": "explicit" if target_drugs is not None else "goal mentions or largest metadata row counts",
            },
        }
        report["summary"] = render_summary(report)
        report["tests"] = self.tests
        return report


    # ----------------------------- data loading ----------------------------- #

    def _find_metadata_file(self, data_dir: Path) -> Path | None:
        preferred = ["patient_metadata", "metadata", "pfs_months", "os_time_adjusted"]
        paths = sorted(
            tabular_files(data_dir),
            key=lambda p: preferred.index(p.stem.lower()) if p.stem.lower() in preferred else len(preferred),
        )
        for path in paths:
            # Arbitrary filenames are supported; identify clinical tables by
            # their headers so a genomic matrix is not mistaken for metadata.
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

        with metadata_path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f, delimiter=table_delimiter(metadata_path))
            for row in reader:
                row = {key.strip().upper(): (value or "").strip() for key, value in row.items() if key is not None}
                sid = next((row[key] for key in SAMPLE_ID_COLUMNS if row.get(key)), "")
                if not sid:
                    continue
                drug = next((row[key] for key in DRUG_COLUMNS if row.get(key)), "").upper()

                # Parse overall survival
                os_val = None
                for os_col in SURVIVAL_COLUMNS:
                    if row.get(os_col):
                        try:
                            os_val = float(row[os_col])
                            break
                        except ValueError:
                            pass
                if os_val is None:
                    os_val = 0.0

                # Parse status (1 = deceased/event, 0 = living/censored)
                status = 0
                for st_col in STATUS_COLUMNS:
                    if row.get(st_col):
                        raw_st = str(row[st_col]).upper()
                        if "DECEASED" in raw_st or "PROGRESSION" in raw_st or "1:" in raw_st or raw_st == "1":
                            status = 1
                        break

                if sid not in samples:
                    samples[sid] = {"os_months": os_val, "status": status, "drugs": set()}
                if drug:
                    samples[sid]["drugs"].add(drug)
                    drugs[drug].append(sid)

        return samples, drugs

    def _select_target_drugs(
        self, goal: str, available_drugs: dict[str, list[str]], override: str | None = None
    ) -> list[str]:
        if override and override.upper() in available_drugs:
            return [override.upper()]

        # Check goal for drug mentions
        goal_upper = goal.upper()
        mentioned = [d for d in available_drugs if d in goal_upper and len(available_drugs[d]) >= 10]
        if mentioned:
            return sorted(mentioned, key=lambda d: len(available_drugs[d]), reverse=True)[:3]

        # Top drugs by cohort size
        sorted_drugs = sorted(available_drugs.items(), key=lambda kv: len(kv[1]), reverse=True)
        return [d for d, sids in sorted_drugs[:4] if len(sids) >= 30]

    # ----------------------------- screening ----------------------------- #

    def _screen_alterations(
        self, data_dir: Path, samples: dict[str, dict[str, Any]], target_drugs: list[str]
    ) -> list[dict[str, Any]]:
        alteration_specs = [
            ("mutation", ["cell2mutation_labeled", "*mutation*", "*mut*"]),
            ("amplification", ["cell2cnamplification_labeled", "*amplification*"]),
            ("deletion", ["cell2cndeletion_labeled", "*deletion*"]),
        ]

        all_candidates: list[dict[str, Any]] = []

        for alt_type, stems in alteration_specs:
            matrix_path = self._find_matrix_file(
                data_dir, [f"{stem}{suffix}" for stem in stems for suffix in TABULAR_SUFFIXES]
            )
            if not matrix_path or not matrix_path.is_file():
                continue
            self.matrix_paths[alt_type] = matrix_path
            for drug in target_drugs:
                drug_candidates = self._screen_single_matrix(matrix_path, alt_type, drug, samples)
                all_candidates.extend(drug_candidates)

        # Sort all candidates by p_value ascending
        all_candidates.sort(key=lambda c: c["p_value"])
        # Dedup to keep strongest alteration/drug pair per gene
        seen: set[tuple[str, str]] = set()
        unique_candidates: list[dict[str, Any]] = []
        for c in all_candidates:
            key = (c["biomarker"], c["drug"])
            if key not in seen:
                seen.add(key)
                unique_candidates.append(c)

        return unique_candidates[:MAX_CANDIDATES]

    def _find_matrix_file(self, data_dir: Path, patterns: list[str]) -> Path | None:
        paths = tabular_files(data_dir)
        for pat in patterns:
            for path in paths:
                if fnmatchcase(path.name.lower(), pat.lower()):
                    return path
        return None

    def _screen_single_matrix(
        self, matrix_path: Path, alt_type: str, drug: str, samples: dict[str, dict[str, Any]]
    ) -> list[dict[str, Any]]:
        target_sids = {sid: info for sid, info in samples.items() if drug in info["drugs"]}
        if len(target_sids) < MIN_COHORT:
            return []

        candidates: list[dict[str, Any]] = []

        try:
            with matrix_path.open(encoding="utf-8-sig", newline="") as f:
                reader = csv.reader(f, delimiter=table_delimiter(matrix_path))
                headers = next(reader, [])
                if len(headers) < 2:
                    return []
                # The first column contains sample IDs, including when its
                # header is blank. csv.reader preserves that blank and quotes.
                genes = [header.strip() for header in headers[1:]]

                mut_os: dict[int, list[float]] = {i: [] for i in range(len(genes))}
                wt_os: dict[int, list[float]] = {i: [] for i in range(len(genes))}
                mut_status: dict[int, list[int]] = {i: [] for i in range(len(genes))}
                wt_status: dict[int, list[int]] = {i: [] for i in range(len(genes))}

                for parts in reader:
                    if not parts or len(parts) < 2:
                        continue
                    sid = parts[0].strip()
                    if sid not in target_sids:
                        continue
                    s_info = target_sids[sid]
                    vals = parts[1:]
                    for i, val in enumerate(vals):
                        if i >= len(genes):
                            break
                        if val.strip().lower() in ("1", "1.0", "true"):
                            mut_os[i].append(s_info["os_months"])
                            mut_status[i].append(s_info["status"])
                        else:
                            wt_os[i].append(s_info["os_months"])
                            wt_status[i].append(s_info["status"])

            for i, gene in enumerate(genes):
                n_alt = len(mut_os[i])
                n_wt = len(wt_os[i])
                if n_alt < MIN_GROUP or n_wt < MIN_GROUP:
                    continue

                u_stat, p_val = stats.mannwhitneyu(
                    mut_os[i], wt_os[i], alternative="two-sided",
                    method="asymptotic", use_continuity=True,
                )

                med_alt = float(np.median(mut_os[i]))
                med_wt = float(np.median(wt_os[i]))
                delta_os = round(med_alt - med_wt, 2)

                # Fisher exact test for mortality difference
                alt_dec = sum(mut_status[i])
                alt_liv = n_alt - alt_dec
                wt_dec = sum(wt_status[i])
                wt_liv = n_wt - wt_dec
                odds_ratio, f_pval = stats.fisher_exact(
                    [[alt_dec, alt_liv], [wt_dec, wt_liv]], alternative="two-sided",
                )
                or_val = round(float(odds_ratio), 2) if np.isfinite(odds_ratio) else None

                relationship = "reduced_response_or_poor_prognosis" if delta_os < 0 else "favorable_response_or_prognosis"

                result = {
                    "biomarker": gene,
                    "alteration_type": alt_type,
                    "drug": drug,
                    "relationship": relationship,
                    "delta_os_months": delta_os,
                    "median_os_altered": round(med_alt, 2),
                    "median_os_wt": round(med_wt, 2),
                    "p_value": float(p_val),
                    "odds_ratio": or_val,
                    "fisher_p_value": float(f_pval),
                    "sample_size": n_alt + n_wt,
                    "altered_samples": n_alt,
                    "unaltered_samples": n_wt,
                    "u_statistic": float(u_stat),
                    "altered_events": alt_dec,
                    "altered_no_event": alt_liv,
                    "unaltered_events": wt_dec,
                    "unaltered_no_event": wt_liv,
                    "odds_ratio_nonfinite": not bool(np.isfinite(odds_ratio)),
                    "nominally_significant": bool(np.isfinite(p_val) and p_val <= ALPHA),
                    "matrix_file": str(matrix_path),
                    "cohort": f"Clinical cohort ({drug})",
                }
                # Preserve nonsignificant results to audit the tested family.
                self.tests.append(result)
                if result["nominally_significant"]:
                    candidates.append(result)
        except Exception as e:
            log.warning("screen_single_matrix_failed", path=str(matrix_path), err=str(e))
            raise ValueError(f"Failed to screen {matrix_path}: {e}") from e

        return candidates


def profile_dataset(
    data_dir: Path, *, goal: str = "", target_drugs: list[str] | None = None,
) -> dict[str, Any]:
    """Run the agent's statistical workflow without a database, session, or LLM."""
    return DatasetProfiler().profile(data_dir, goal=goal, target_drugs=target_drugs)


def tests_csv(tests: list[dict[str, Any]]) -> str:
    """Export the complete tested family, including all contingency table cells."""
    columns = [
        "biomarker", "alteration_type", "drug", "sample_size", "altered_samples", "unaltered_samples",
        "u_statistic", "p_value", "nominally_significant", "median_os_altered", "median_os_wt",
        "delta_os_months", "altered_events", "altered_no_event", "unaltered_events", "unaltered_no_event",
        "odds_ratio", "odds_ratio_nonfinite", "fisher_p_value", "relationship", "matrix_file",
    ]
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(tests)
    return output.getvalue()


def render_summary(report: dict[str, Any]) -> str:
    """Explain the actual tests, threshold, selection, and input provenance."""
    parts = [
        "# Dataset & Biomarker Profiling Summary",
        "",
        f"- Unique sample IDs loaded from clinical metadata: **{report['sample_count']}**",
        f"- Targeted treatment arms screened: **{', '.join(report['drugs'])}**",
        f"- Gene/alteration/treatment comparisons tested: **{report['selection']['eligible_tests']}**",
        f"- Nominally significant comparisons (unadjusted p ≤ {ALPHA}): **{report['selection']['nominally_significant_tests']}**",
        f"- Candidate associations reported after deduplication and the top-{MAX_CANDIDATES} limit: **{len(report['candidates'])}**",
        "",
        "## Statistical methods and significance",
        "",
        "- Primary test: **two-sided Mann-Whitney U** (`scipy.stats.mannwhitneyu`), comparing the recorded "
        "duration distributions of altered and unaltered samples within each treatment arm. "
        "The null hypothesis is equal distributions, rather than specifically equal medians.",
        "- P-values use `method='asymptotic'`, with tie correction and `use_continuity=True`.",
        f"- **Statistical significance means a finite, unadjusted primary p-value ≤ {ALPHA}.** "
        "No multiple-testing correction or false discovery rate control is applied. These are nominal, exploratory associations.",
        f"- Eligibility: at least {MIN_COHORT} metadata samples exposed to a treatment and at least "
        f"{MIN_GROUP} altered and {MIN_GROUP} unaltered matched matrix rows per gene. The unit is a sample ID, not necessarily a unique patient.",
        "- Secondary test: **two-sided Fisher's exact test** (`scipy.stats.fisher_exact`) on "
        "`[[altered event, altered no-event], [unaltered event, unaltered no-event]]`. "
        "Its null hypothesis is an odds ratio of 1. Fisher p-values do **not** filter or rank candidates. "
        "Nonfinite odds ratios are stored as null, not as 1.",
        "- Effect size: median recorded duration in altered samples minus that in unaltered samples, rounded to two decimals. "
        "Direction labels describe this difference; the U test does not directly test the median difference.",
        f"- Reporting: sort by primary p-value, retain the strongest alteration for each gene/treatment pair, "
        f"then show at most {MAX_CANDIDATES} candidates. The number shown is not the total number passing the threshold.",
        "",
        "## Data handling and interpretation",
        "",
        "- Clinical columns: first nonempty ID among `SAMPLE_ID`, `PATIENT_ID`, `sample`, `id`; "
        "first parseable duration among `OS_MONTHS`, `PFS_MONTHS`, `survival_months`, `time`. "
        "The OS labels in the data exports are legacy field names; a fallback column can represent another endpoint.",
        "- Repeated sample IDs retain the first metadata row's duration/status and merge treatment exposures. "
        "Missing/unparseable durations become 0.0. Missing or unrecognized status becomes no-event; "
        "statuses containing `DECEASED`, `PROGRESSION`, `1:`, or exactly `1` become event.",
        "- Matrix values `1`, `1.0`, or `true` (case-insensitive) mean altered; all other present values, "
        "including blank cells, are treated as unaltered. Unmatched sample IDs are ignored; repeated matched matrix rows count repeatedly.",
        "- **Censoring is not accounted for in the duration comparison**: this is not a log-rank test or Cox model. "
        "Treatment cohorts can overlap, and no adjustment is made for confounding or repeated patients. "
        "These associations alone do not establish treatment-specific benefit or a causal biomarker effect.",
        "",
        "## Top Candidate Biomarkers Associated With Treatment Response",
        "",
    ]
    if not report["candidates"]:
        parts.append(f"*(No candidate alterations reached nominal statistical significance p ≤ {ALPHA}.)*")
    else:
        parts.extend([
            "| Gene | Alteration | Drug | Δ median months | Mann-Whitney U | Primary p | Fisher p | Altered / unaltered N |",
            "| :--- | :--- | :--- | ---: | ---: | ---: | ---: | ---: |",
        ])
        for c in report["candidates"]:
            parts.append(
                f"| **{c['biomarker']}** | {c['alteration_type']} | {c['drug']} | "
                f"{c['delta_os_months']:+.2f} | {c['u_statistic']:g} | {c['p_value']:.4e} | "
                f"{c['fisher_p_value']:.4e} | {c['altered_samples']} / {c['unaltered_samples']} |"
            )
    parts.extend([
        "", "## Reproducibility", "",
        f"- Generated at: `{report['generated_at']}` (UTC).",
        f"- Software: Python {report['software']['python']}; NumPy {report['software']['numpy']}; SciPy {report['software']['scipy']}.",
        "- Full comparisons, including nonsignificant results and Fisher table counts: `statistical_tests.csv`.",
        "- Methods, selected candidates, selection counts, and input hashes: `biomarker_candidates.json`.",
    ])
    for role, info in report["inputs"].items():
        parts.append(f"- {role}: `{info['path']}` ({info['bytes']} bytes); SHA-256 `{info['sha256']}`.")
    parts.extend([
        "", "Method references: [SciPy Mann-Whitney U](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.mannwhitneyu.html), "
        "[SciPy Fisher exact test](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.fisher_exact.html).", "",
    ])
    return "\n".join(parts)
