# Biomarker survival analysis and independent validation

In a research session the data comes from **attachments** (files uploaded with
the question, `co-scientist run --attach`, or `POST /api/sessions`), not from a
`data/` folder. The planning step sees a short description of each attachment and
selects the tabular ones; the Supervisor then enqueues `ProfileDataset`.
`DataAnalysisAgent` copies the selected attachments into a temporary directory and
calls `profile_dataset` in `co_scientist/analysis.py`, which reads flat clinical
and alteration tables and runs lifelines survival analysis. The agent stores the
report, statistics, per-candidate survival points and PNG plots in the database
(`analysis_reports`, `analysis_points` and the GridFS `plots` bucket on Atlas) and
writes no files. Read them from `GET /api/sessions/{id}/analysis` and
`GET /api/sessions/{id}/plots/{name}` (see [frontend-api.md](frontend-api.md)).
The standalone runner below uses the same calculation without a database,
session, LLM, or API key, and does write files.

## Run separately

Install the project dependencies, including lifelines and matplotlib, in the
project's Python environment. From the repository root:

```bash
.venv/bin/python scripts/validate_data_analysis.py --data-dir ./data \
  --drug FLUOROURACIL --drug LEUCOVORIN --drug OXALIPLATIN --drug CAPECITABINE \
  --output-dir ./data/kaplan_meier
```

To validate a previous **Kaplan-Meier/log-rank** run, supply its artifact:

```bash
.venv/bin/python scripts/validate_data_analysis.py --data-dir ./data \
  --reference ./data/kaplan_meier/biomarker_candidates.json \
  --output-dir ./data/validation
```

A reference fixes the treatment selection and compares the analysis method,
candidate order, sample count, treatment list, and every stored candidate field.
Numeric comparisons use relative tolerance `1e-10` and **zero absolute tolerance**,
so `1e-100` and `2e-100` differ. References from the former Mann-Whitney/Fisher
analysis produce an expected **method mismatch**: those p-values and raw medians
are different quantities. The old method is not rerun.

Exit codes are 0 for success/match, 1 for a mismatch, and 2 for invalid input or a
calculation error. The reference artifact is preserved. Neither a matching
calculation nor a method comparison reconstructs missing historical input hashes.

Without explicit `--drug` arguments or a reference, `--goal` can select up to
three mentioned treatments with at least 10 eligible metadata rows each.
Otherwise up to four treatments with at least 30 eligible metadata rows are
selected by row count. Duplicate valid metadata rows contribute to treatment
selection counts; statistical eligibility uses unique sample IDs.

## Statistical methods and significance

For each treatment, gene, and alteration type, the profiler fits a separate
**Kaplan-Meier survival curve** for altered and unaltered samples using
`lifelines.KaplanMeierFitter`. Event flags are always passed explicitly:
`1` is an observed death/progression event and `0` is right-censoring. Curves use
95% Greenwood log-log confidence intervals. See the
[lifelines KaplanMeierFitter documentation](https://lifelines.readthedocs.io/en/latest/fitters/univariate/KaplanMeierFitter.html).

Kaplan-Meier estimates survival; the **unweighted two-group log-rank test**
(`lifelines.statistics.logrank_test`) supplies the comparison statistic and
p-value. Its null hypothesis is equal hazards/survival functions between groups.
The statistic uses a chi-squared reference distribution with one degree of
freedom. It assumes independent censoring and has greatest power under
proportional hazards; crossing curves can reduce its ability to detect differences.
See the [lifelines log-rank documentation](https://lifelines.readthedocs.io/en/latest/lifelines.statistics.html#lifelines.statistics.logrank_test).

Raw log-rank p-values are retained for every eligible comparison. Candidate
significance requires a finite **Benjamini–Hochberg adjusted q-value ≤ 0.05**,
with the false discovery rate controlled across all eligible gene, alteration,
and treatment tests in the session.
A treatment needs at least 20 eligible metadata sample IDs; a gene needs at
least 10 altered and 10 unaltered matched samples.

Effects are the **KM median survival times**, rather than medians of raw
follow-up durations. A KM median that is not reached is stored as null and shown
as `NR`. A median difference is calculated only when both medians are finite;
otherwise its value is null and its direction is undetermined.

FDR-significant results are sorted by raw log-rank p-value. The strongest
alteration per gene/treatment pair is retained, then the report is limited to
12 candidates. Nominal and FDR-significant test counts are reported separately
from that display cap.

## Survival plots and outputs

This section describes the standalone runner's files. In a research session the
same content is stored in the database: the summary text is `summary_markdown` in
the analysis report, and each plot is a stored PNG served by URL.

`summary.md` retains the methods, data handling, candidate table, and
reproducibility sections and adds **Kaplan-Meier survival curves for the top 3
biomarkers**. Each distinct gene appears once, using its strongest significant
alteration/treatment association. If fewer than three genes qualify, all
available genes are plotted; an empty screen explains why there are no plots.

Each PNG shows altered versus unaltered step curves, 95% confidence bands,
censor marks, log-rank p-value/statistic and adjusted q-value, sample/event counts, and a table of
numbers at risk just before the displayed times. Images use relative Markdown
links under `plots/`, so the summary and plots can be moved together.

The other outputs are:

- `biomarker_candidates.json`: selected candidates, method parameters,
  endpoint, exclusions, software versions, input hashes, and aggregate survival
  probabilities/confidence intervals/event tables for the plotted associations.
- `statistical_tests.csv`: every eligible comparison, including nonsignificant
  tests, log-rank statistics, raw p-values, adjusted q-values, KM medians, and event/censoring counts.
- `validation.json`: reference comparison and differences, when requested.

The session agent produces the same plots and statistics for new research runs
and stores them in the database. Downstream evidence labels identify KM median
differences, log-rank p-values, and adjusted q-values.

## Separate literature overview

Full research sessions retain **both** outputs when generation uses the
`data_driven` strategy:

- **The analysis report**: empirical survival statistics and plots, stored when
  dataset profiling finishes. Read it at `GET /api/sessions/{id}/analysis`; its
  `summary_markdown` field is the text that used to be `summary.md`.
- **The overview**: the literature and mechanistic synthesis, written by
  meta-review when the research session finishes, after hypothesis generation,
  review, and ranking. It is stored as a synthesis document and the session
  points to it as `db:syntheses/<session_id>`.

Meta-review receives the recorded literature sources and the dataset summary as
context. The two are separate documents: the overview does not link to a file; fetch the
analysis report separately. Finalization preserves the
analysis report, including when it writes a fallback overview after a
meta-review failure or a no-op. With no hypotheses, that fallback explicitly
states that no literature synthesis was available.
`co-scientist report <session_id>` displays the overview (read via
`db:syntheses/<session_id>`; sessions from before the move still read their old
`final/overview.md`).

The standalone statistical validation script does not run the research agents
or generate a literature overview.

## Data handling and interpretation

The table uses a **single endpoint**, selected in order from `OS_MONTHS`,
`PFS_MONTHS`, `survival_months`, and `time`, paired with a matching event column.
OS duration is not paired with PFS status. Generic `status` or `event` is accepted.
Durations are interpreted as months. Missing, negative, or nonfinite durations
and unknown event statuses are excluded and counted rather than imputed.

Sample ID falls back to patient ID. Repeated metadata IDs retain the first valid
duration/status and merge treatment exposures. A repeated matched matrix ID is
counted once. Matrix values `1`, `1.0`, or `true` mean altered; `0`, `0.0`, or
`false` mean unaltered. Other values, including blank or absent cells, are
excluded for that gene. Metadata and matrix exclusions are reported in JSON.

The analysis accounts for **right-censoring**, but does not adjust for clinical
covariates, overlapping treatment exposures, or multiple samples from one
patient. These are exploratory survival associations rather than evidence of
causal biomarker effects or treatment-specific benefit.

## Regression tests

```bash
.venv/bin/pytest co_scientist/tests/unit/test_statistical_analysis.py \
  co_scientist/tests/unit/test_data_analysis.py \
  co_scientist/tests/unit/test_data_driven_outputs.py \
  co_scientist/tests/unit/test_artifacts.py -q
```

Tests check hand-derived censored KM probabilities, independently constructed
lifelines fits and log-rank inputs, significance boundaries, unreached medians,
invalid records, distinct biomarker selection, actual PNG output, relative image
links, independent rerun validation, and safe binary artifact writes.
The data-driven workflow test also checks that final meta-review writes a
separate literature overview while preserving the dataset summary and plots.
