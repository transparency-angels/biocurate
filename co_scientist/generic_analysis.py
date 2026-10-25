"""Exploratory statistical profiling for tabular uploads without a survival schema.

This deliberately reports descriptive summaries and raw group-test statistics
with Benjamini-Hochberg adjusted q-values. It does not infer causality or silently select an
outcome from arbitrary data.
"""

from __future__ import annotations

import csv
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from scipy.stats import kruskal, mannwhitneyu, spearmanr

from .storage.datasets import table_delimiter, tabular_files

MAX_CORRELATION_COLUMNS = 40
MAX_SUMMARY_COLUMNS = 200
MAX_GROUP_COLUMNS = 8
MAX_GROUP_TESTS = 20_000
MAX_REPORTED_GROUP_TESTS = 100


def _read_table(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="", errors="replace") as stream:
        reader = csv.DictReader(stream, delimiter=table_delimiter(path))
        headers = [str(name or "").strip() for name in (reader.fieldnames or [])]
        rows = []
        for row in reader:
            rows.append({name: str(row.get(name) or "").strip() for name in headers})
        return headers, rows


def _numeric(values: list[str]) -> np.ndarray:
    parsed = []
    for value in values:
        try:
            number = float(value)
            parsed.append(number if math.isfinite(number) else np.nan)
        except (TypeError, ValueError):
            parsed.append(np.nan)
    return np.asarray(parsed, dtype=float)


def _id_column(headers: list[str]) -> str | None:
    aliases = {"sampleid", "patientid", "subjectid", "specimenid", "sample", "patient", "subject", "specimen"}
    return next((header for header in headers if "".join(ch for ch in header.lower() if ch.isalnum()) in aliases), None)


def _field_name(header: str) -> str:
    return header.rsplit(":", 1)[-1].strip().lower()


def _bh(p_values: list[float]) -> list[float]:
    """Benjamini-Hochberg adjusted p-values, restored to original order."""
    n = len(p_values)
    order = sorted(range(n), key=p_values.__getitem__)
    adjusted = [1.0] * n
    running = 1.0
    for rank_index in range(n - 1, -1, -1):
        original = order[rank_index]
        rank = rank_index + 1
        running = min(running, p_values[original] * n / rank)
        adjusted[original] = min(1.0, running)
    return adjusted


def _fmt(value: float | int | None, digits: int = 3) -> str:
    if value is None or not math.isfinite(float(value)):
        return "—"
    return f"{value:.{digits}g}"


def profile_generic_dataset(data_dir: Path) -> dict[str, Any]:
    """Summarise arbitrary uploaded tables and test obvious group associations."""
    files = tabular_files(data_dir)
    tables: list[dict[str, Any]] = []
    tests: list[dict[str, Any]] = []
    join_audit: dict[str, Any] | None = None
    datasets = []
    for path in files:
        headers, rows = _read_table(path)
        datasets.append((path.name, headers, rows, _id_column(headers)))

    # Uploads often split sample annotations and measurements across files.
    # Join those on an explicit identifier; exclude duplicated IDs on each side
    # so technical repeats are not accidentally counted as independent samples.
    joinable = [item for item in datasets if item[3] is not None]
    if len(joinable) > 1:
        keyed = []
        duplicate_ids_excluded: dict[str, int] = {}
        for name, headers, rows, id_column in joinable:
            assert id_column is not None
            counts: dict[str, int] = {}
            for row in rows:
                key = row.get(id_column, "").strip()
                if key:
                    counts[key] = counts.get(key, 0) + 1
            unique = {row[id_column].strip(): row for row in rows
                      if row.get(id_column, "").strip() and counts[row[id_column].strip()] == 1}
            duplicate_ids_excluded[name] = sum(count > 1 for count in counts.values())
            keyed.append((name, id_column, headers, unique))
        sample_ids = sorted(set().union(*(set(item[3]) for item in keyed)))
        join_audit = {
            "tables": [item[0] for item in keyed], "joined_ids": len(sample_ids),
            "duplicate_ids_excluded": duplicate_ids_excluded,
        }
        headers = ["sample_id"] + [f"{name}:{header}" for name, id_col, cols, _ in keyed for header in cols if header != id_col]
        rows = []
        for sample_id in sample_ids:
            merged = {"sample_id": sample_id}
            for name, id_col, cols, keyed_rows in keyed:
                source = keyed_rows.get(sample_id, {})
                merged.update({f"{name}:{header}": source.get(header, "") for header in cols if header != id_col})
            rows.append(merged)
        datasets.append(("Combined tables (joined by sample ID)", headers, rows, "sample_id"))

    for table_name, headers, rows, id_column in datasets:
        if not headers:
            tables.append({"name": table_name, "rows": len(rows), "headers": [], "warnings": ["No header row was detected."]})
            continue
        n = len(rows)
        if not n:
            tables.append({"name": table_name, "rows": 0, "headers": headers, "warnings": ["The table has a header but no data rows."]})
            continue

        columns: dict[str, list[str]] = {header: [row.get(header, "") for row in rows] for header in headers}
        numeric: dict[str, np.ndarray] = {}
        categorical: dict[str, list[str]] = {}
        summaries: list[dict[str, Any]] = []
        for column_index, (header, values) in enumerate(columns.items()):
            nonempty = [value for value in values if value]
            missing = n - len(nonempty)
            keep_summary = column_index < MAX_SUMMARY_COLUMNS
            if header == id_column:
                if keep_summary:
                    summaries.append({"column": header, "kind": "identifier", "n": len(nonempty), "missing": missing, "unique": len(set(nonempty))})
                continue
            parsed = _numeric(values)
            valid = parsed[np.isfinite(parsed)]
            if header != id_column and nonempty and len(valid) / len(nonempty) >= 0.8 and len(valid) >= 2:
                numeric[header] = parsed
                if keep_summary:
                    summaries.append({
                        "column": header, "kind": "numeric", "n": int(len(valid)), "missing": missing,
                        "mean": float(np.mean(valid)), "sd": float(np.std(valid, ddof=1)) if len(valid) > 1 else None,
                        "median": float(np.median(valid)), "q1": float(np.quantile(valid, .25)),
                        "q3": float(np.quantile(valid, .75)), "min": float(np.min(valid)), "max": float(np.max(valid)),
                    })
            elif nonempty:
                counts: dict[str, int] = {}
                for value in nonempty:
                    counts[value] = counts.get(value, 0) + 1
                if 1 < len(counts) <= max(20, int(n * 0.5)):
                    categorical[header] = values
                if keep_summary:
                    summaries.append({
                        "column": header, "kind": "categorical/text", "n": len(nonempty), "missing": missing,
                        "levels": len(counts), "top": sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:5],
                    })
            else:
                if keep_summary:
                    summaries.append({"column": header, "kind": "empty", "n": 0, "missing": n})

        duplicate_rows = n - len({tuple(row.get(header, "") for header in headers) for row in rows})
        tables.append({
            "name": table_name, "rows": n, "columns": len(headers), "duplicate_rows": duplicate_rows,
            "missing_cells": sum(not row.get(header, "") for row in rows for header in headers),
            "summaries": summaries,
        })

        # Screen a small, explicit set of plausible grouping columns first, then
        # other low-cardinality categorical columns. Non-parametric tests avoid
        # assuming normally distributed measurements.
        preferred = ("group", "condition", "treatment", "arm", "cohort", "status", "class", "diagnosis", "phenotype")
        # 0/1 outcome or treatment fields are numeric in storage but categorical
        # in the experimental design.
        for header in headers:
            if header == id_column or _field_name(header) not in preferred or header not in numeric:
                continue
            codes = [str(int(value)) if np.isfinite(value) else "" for value in numeric[header]]
            if 2 <= len({code for code in codes if code}) <= 5:
                categorical[header] = codes
        groups = sorted(categorical, key=lambda col: (0 if _field_name(col) in preferred else 1, col.lower()))[:MAX_GROUP_COLUMNS]
        measured = list(numeric)
        for group_col in groups:
            labels = columns[group_col]
            levels = sorted({value for value in labels if value})
            if not 2 <= len(levels) <= 5:
                continue
            for value_col in measured:
                if value_col == group_col:
                    continue
                group_values = []
                names = []
                for level in levels:
                    vals = [numeric[value_col][i] for i, label in enumerate(labels) if label == level and np.isfinite(numeric[value_col][i])]
                    if len(vals) >= 3:
                        names.append(level)
                        group_values.append(np.asarray(vals, dtype=float))
                if len(group_values) < 2:
                    continue
                try:
                    if len(group_values) == 2:
                        result = mannwhitneyu(group_values[0], group_values[1], alternative="two-sided", method="auto")
                        n1, n2 = len(group_values[0]), len(group_values[1])
                        delta = float(np.median(group_values[0]) - np.median(group_values[1]))
                        effect = float(2 * result.statistic / (n1 * n2) - 1)
                        test_name = "Mann–Whitney U"
                    else:
                        result = kruskal(*group_values)
                        total_n = sum(map(len, group_values))
                        effect = max(0.0, float((result.statistic - len(group_values) + 1) / (total_n - len(group_values))))
                        delta = None
                        test_name = "Kruskal–Wallis"
                    p = float(result.pvalue)
                    if math.isfinite(p):
                        tests.append({
                            "table": table_name, "group": group_col, "measure": value_col,
                            "groups": [{"name": name, "n": len(vals), "median": float(np.median(vals))} for name, vals in zip(names, group_values, strict=True)],
                            "test": test_name, "statistic": float(result.statistic), "p_value": p,
                            "effect_size": effect, "effect_size_name": "rank-biserial correlation" if len(group_values) == 2 else "epsilon-squared",
                            "median_difference": delta,
                        })
                except (ValueError, TypeError):
                    continue
                if len(tests) >= MAX_GROUP_TESTS:
                    break
            if len(tests) >= MAX_GROUP_TESTS:
                break

    if tests:
        q_values = _bh([test["p_value"] for test in tests])
        for test, q_value in zip(tests, q_values, strict=True):
            test["q_value"] = q_value
            test["fdr_significant"] = q_value <= 0.05

    # Rank monotonic relationships across numeric measures; report only the
    # strongest, with FDR adjustment over all tested pairs in each table.
    correlations: list[dict[str, Any]] = []
    for table_name, headers, rows, id_column in datasets:
        if not headers or not rows:
            continue
        numeric = {}
        for header in headers:
            if header == id_column:
                continue
            vals = _numeric([row.get(header, "") for row in rows])
            if np.isfinite(vals).sum() >= 5 and np.isfinite(vals).sum() / max(1, len(rows)) >= .8:
                numeric[header] = vals
        names = list(numeric)[:MAX_CORRELATION_COLUMNS]
        family: list[dict[str, Any]] = []
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                mask = np.isfinite(numeric[a]) & np.isfinite(numeric[b])
                if int(mask.sum()) < 5:
                    continue
                with np.errstate(invalid="ignore"):
                    result = spearmanr(numeric[a][mask], numeric[b][mask])
                if math.isfinite(float(result.statistic)) and math.isfinite(float(result.pvalue)):
                    family.append({"table": table_name, "x": a, "y": b, "n": int(mask.sum()), "rho": float(result.statistic), "p_value": float(result.pvalue)})
        if family:
            qs = _bh([item["p_value"] for item in family])
            for item, q in zip(family, qs, strict=True):
                item["q_value"] = q
            correlations.extend(sorted(family, key=lambda item: (item["q_value"], -abs(item["rho"])))[:10])

    row_count = max((table["rows"] for table in tables), default=0)
    report: dict[str, Any] = {
        "profile_type": "exploratory_tabular", "sample_count": row_count,
        "generated_at": datetime.now(UTC).isoformat(), "tables": tables,
        "group_comparisons": sorted(tests, key=lambda item: item["q_value"])[:MAX_REPORTED_GROUP_TESTS],
        "group_comparisons_total": len(tests), "correlations": correlations,
        "join_audit": join_audit,
        "screening": {"max_group_columns_per_table": MAX_GROUP_COLUMNS,
                      "max_group_tests": MAX_GROUP_TESTS,
                      "reported_group_tests": MAX_REPORTED_GROUP_TESTS,
                      "summary_columns_per_table": MAX_SUMMARY_COLUMNS,
                      "max_numeric_columns_for_correlations": MAX_CORRELATION_COLUMNS,
                      "group_test_cap_reached": len(tests) >= MAX_GROUP_TESTS},
        "candidates": [], "points": {}, "drugs": [], "tests": [], "survival_curves": [],
        "selection": {"type": "exploratory", "group_comparisons": len(tests), "correlations": len(correlations)},
        "methods": {
            "descriptive": "mean, sample SD, median, IQR, min/max; categorical counts; missingness and duplicate rows",
            "group_tests": "Mann–Whitney U for two groups; Kruskal–Wallis for three to five groups",
            "correlations": "Spearman rank correlation",
            "multiple_testing": "Benjamini–Hochberg false discovery rate (q-values), separately for group tests and within-table correlations",
            "interpretation": "exploratory associations; no causal or covariate-adjusted inference",
        },
    }
    report["summary"] = _render_summary(report)
    return report


def _render_summary(report: dict[str, Any]) -> str:
    parts = ["# Exploratory dataset analysis", "", "Descriptive profiling of the uploaded tables, with non-parametric group comparisons and rank correlations where the table structure supports them. These analyses are exploratory and do not establish causality.", ""]
    if report["group_comparisons_total"]:
        parts += [f"Screened **{report['group_comparisons_total']}** group/measure combinations; showing up to {MAX_REPORTED_GROUP_TESTS} results ordered by FDR q-value.", ""]
    join = report.get("join_audit")
    if join:
        parts += [
            "## Sample matching across files", "",
            f"Joined {len(join['tables'])} tables on exact sample/patient IDs, producing {join['joined_ids']} unique IDs. "
            "Rows with duplicate IDs were excluded from that file's contribution to the joined table; IDs missing from a file are retained as missing values.",
            "",
        ]
        if join["duplicate_ids_excluded"]:
            parts.append("Duplicate IDs excluded by file: " + ", ".join(f"{name}: {count}" for name, count in join["duplicate_ids_excluded"].items()) + ".")
            parts.append("")
    for table in report["tables"]:
        parts += [f"## {table['name']}", ""]
        if table.get("warnings"):
            parts += ["; ".join(table["warnings"]), ""]
            continue
        parts += [f"**{table['rows']} rows · {table['columns']} columns · {table['duplicate_rows']} duplicate rows · {table['missing_cells']} missing cells**", ""]
        summaries = table["summaries"]
        numeric = [item for item in summaries if item["kind"] == "numeric"]
        categorical = [item for item in summaries if item["kind"] == "categorical/text"]
        if numeric:
            parts += ["### Numeric measures", "", "| Measure | n | Missing | Mean ± SD | Median (IQR) | Range |", "| --- | ---: | ---: | ---: | ---: | ---: |"]
            for item in numeric:
                sd = _fmt(item["sd"])
                parts.append(f"| {item['column']} | {item['n']} | {item['missing']} | {_fmt(item['mean'])} ± {sd} | {_fmt(item['median'])} ({_fmt(item['q1'])}–{_fmt(item['q3'])}) | {_fmt(item['min'])}–{_fmt(item['max'])} |")
            parts.append("")
        if categorical:
            parts += ["### Categorical and text fields", "", "| Field | n | Missing | Levels | Most frequent values |", "| --- | ---: | ---: | ---: | --- |"]
            for item in categorical:
                top = ", ".join(f"{name} ({count})" for name, count in item["top"])
                parts.append(f"| {item['column']} | {item['n']} | {item['missing']} | {item['levels']} | {top} |")
            parts.append("")
    parts += ["## Group comparisons", ""]
    if report["group_comparisons"]:
        parts += ["| Table | Measure by group | Method | Group medians (n) | Effect size | p | FDR q |", "| --- | --- | --- | --- | ---: | ---: | ---: |"]
        for test in sorted(report["group_comparisons"], key=lambda item: item["q_value"])[:30]:
            groups = ", ".join(f"{g['name']}: {_fmt(g['median'])} (n={g['n']})" for g in test["groups"])
            parts.append(f"| {test['table']} | {test['measure']} by {test['group']} | {test['test']} | {groups} | {_fmt(test['effect_size'])} ({test['effect_size_name']}) | {_fmt(test['p_value'])} | {_fmt(test['q_value'])} |")
        parts.append("")
        parts.append("Group tests require at least three non-missing observations in each group. q-values control the false discovery rate across the screened group comparisons; treat them as exploratory evidence, not confirmation.")
    else:
        parts.append("No suitable low-cardinality group field and numeric measure combination was found. Review the field summaries above and provide a clearly labelled condition, treatment, or outcome column if group comparisons are intended.")
    if report["screening"]["group_test_cap_reached"]:
        parts.append(f"The group-comparison screen reached its {MAX_GROUP_TESTS:,}-test safety cap; later variable combinations were not tested.")
    parts += ["", "## Correlations", ""]
    if report["correlations"]:
        parts += ["| Table | Measures | Spearman ρ | p | FDR q | n |", "| --- | --- | ---: | ---: | ---: | ---: |"]
        for item in report["correlations"][:30]:
            parts.append(f"| {item['table']} | {item['x']} / {item['y']} | {_fmt(item['rho'])} | {_fmt(item['p_value'])} | {_fmt(item['q_value'])} | {item['n']} |")
        parts.append("")
        parts.append("Correlations describe monotonic association. They do not establish direction of causation and may reflect confounding or repeated measurements.")
    else:
        parts.append("At least two numeric measures with sufficient complete observations are needed to estimate correlations.")
    parts += ["", "## Methods and limitations", "", f"Numeric summaries use available finite values; missing values are not imputed. Group comparisons use Mann–Whitney U (two groups) or Kruskal–Wallis (three to five groups), with Benjamini–Hochberg q-values. Numeric associations use Spearman rank correlation, with q-values adjusted within each table. At most {MAX_GROUP_COLUMNS} categorical grouping fields per table are screened; Spearman correlations use the first {MAX_CORRELATION_COLUMNS} eligible numeric columns to keep the pairwise screen bounded. Field summaries show at most the first {MAX_SUMMARY_COLUMNS} columns per table; group comparisons scan all numeric columns up to the safety cap. Analyses do not adjust for covariates, repeated measures, batch effects, or study design. Validate the unit of observation and prespecify primary outcomes before drawing scientific conclusions."]
    return "\n".join(parts)
