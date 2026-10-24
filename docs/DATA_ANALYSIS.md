# Biomarker statistics and independent validation

The Supervisor detects tabular inputs and enqueues `ProfileDataset`. The
`DataAnalysisAgent` in `co_scientist/agents/data_analysis.py` fetches the session's
goal and calls `profile_dataset` in `co_scientist/analysis.py`. The calculation
reads flat input tables. It does not query the session database for clinical
observations or use an LLM. `storage/artifacts.py` writes its report to
`data/artifacts/<session_id>/data_analysis/summary.md`.

The agent and standalone runner use the same statistical implementation, so a
standalone rerun checks current data against stored numbers without starting
the research workflow. Unit tests in `test_statistical_analysis.py` also check
the calculations against independently constructed sample vectors and 2×2
tables, verify the significance boundary, and exercise reporting and validation.

## Run separately

From the repository root, using its Python environment:

```bash
.venv/bin/python scripts/validate_data_analysis.py --data-dir ./data \
  --reference data/artifacts/<session_id>/data_analysis/biomarker_candidates.json \
  --output-dir ./data/validation
```

The runner needs no database, session, LLM, API key, or network. With a reference,
it reuses the stored treatment selection by default, recomputes the entire
screen, and compares the reported candidate order, sample count, treatment list,
and every original candidate field. Numeric comparisons use relative tolerance
`1e-10` with **zero absolute tolerance**, so values such as `1e-100` and `2e-100`
are treated as different. It preserves the reference file and requires a separate
output destination. Exit codes are 0 for success/match, 1 for a mismatch, and 2
for invalid input or a calculation error.

For a new analysis, omit `--reference`. Optionally supply a `--goal` or repeat
`--drug NAME` for explicit treatment arms. Otherwise the profiler selects up to
four treatments with at least 30 metadata rows each; goal mentions can select
up to three treatments with at least 10 rows each. These selection counts include
duplicate metadata rows. Statistical eligibility is checked separately.

Outputs:

- `summary.md`: test definitions, the significance rule, selection counts,
  group sizes, U statistics, primary and secondary p-values, input hashes,
  Python/NumPy/SciPy versions, and the rerun command.
- `biomarker_candidates.json`: selected candidates, method parameters,
  selection counts, and provenance.
- `statistical_tests.csv`: every successfully computed eligible comparison,
  including nonsignificant results, group medians and sizes, and all four
  Fisher contingency-table cells.
- `validation.json`: reference comparison and mismatches, when a reference
  was requested. Matching numbers validate the current inputs; historical
  file hashes and package versions cannot be reconstructed from older reports.

Run the regression tests separately:

```bash
.venv/bin/pytest co_scientist/tests/unit/test_statistical_analysis.py \
  co_scientist/tests/unit/test_data_analysis.py -q
```

## Tests and significance

For each alteration matrix and selected treatment, samples exposed to the
treatment are split by each gene's binary alteration value. The treatment must
have at least 20 metadata sample IDs, and the matched matrix rows must contain
at least 10 altered and 10 unaltered observations.

The primary test is a **two-sided Mann-Whitney U test** on the recorded durations.
The null hypothesis is equal distributions. It is not specifically a test of
equal medians. The implementation uses SciPy's asymptotic method with tie and
continuity corrections. This is equivalent to the previous automatic method
for the permitted group sizes. See the [SciPy documentation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.mannwhitneyu.html).

**Nominal statistical significance is defined as a finite primary p-value
≤ 0.05.** No correction for multiple comparisons or control of false discovery
rate is applied. The original code accepted `p == 0.05` even though its empty
report text said `< 0.05`; the report now describes the actual inclusive rule.

A secondary **two-sided Fisher's exact test** compares event proportions using
`[[altered event, altered no-event], [unaltered event, unaltered no-event]]`.
Its null hypothesis is an odds ratio of 1. Its p-value does not select or rank
candidates. Nonfinite odds ratios are now recorded as null with a flag rather
than being replaced with 1. See the [SciPy documentation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.fisher_exact.html).

The effect reported is the altered median minus the unaltered median, rounded
to two decimals. Results are sorted by the primary p-value, deduplicated to keep
the strongest alteration per gene/treatment pair, then limited to 12 candidates.
The reported candidate count is therefore different from the total count of
nominally significant comparisons.

## Existing data handling and interpretation

Metadata uses a sample ID where available, falling back to patient ID. Repeated
sample IDs retain the first row's duration and status, while merging treatments.
The first parseable duration among `OS_MONTHS`, `PFS_MONTHS`, `survival_months`,
and `time` is used. Missing/unparseable durations become 0.0; missing or unknown
status is treated as no-event. Thus legacy OS field names may represent a
different endpoint when fallback columns were loaded.

Matrix values `1`, `1.0`, and `true` mean altered. Other present values, including
blank cells, are treated as unaltered. Unmatched sample IDs are ignored. Repeated
matched matrix rows count repeatedly. These policies are documented to reproduce
existing runs; the validation workflow does not silently change them.

The duration comparison does **not** account for censoring and is neither a
log-rank test nor a Cox model. It applies no adjustment for clinical covariates,
overlapping treatment exposures, or multiple samples from the same patient.
Consequently the report describes exploratory, unadjusted associations rather
than establishing treatment-specific benefit or causal biomarker effects.
