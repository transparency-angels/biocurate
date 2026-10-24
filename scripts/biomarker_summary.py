"""Pre-compute biomarker x treatment-response statistics for the agents.

The agents cannot run statistics themselves, so this script does it once and
writes the results into the workspace folder they read from:

  workspace/biomarker_summary.md        short, ranked findings (fits one file_read)
  workspace/biomarker_associations.csv  every test, for anyone who wants to dig

Method, per treatment cohort (drug class, or one of the most-used drugs):
  * one line of therapy per patient -- the earliest line in that cohort
  * a patient counts as "altered" for a gene if any of their samples has it
  * PFS of altered vs unaltered patients: log-rank test, Peto hazard ratio
  * predictive check: the same gene's HR in every *other* cohort, and a z-test
    on the difference, so purely prognostic genes can be told apart
  * Benjamini-Hochberg q-values across all tests
Overall survival (all patients, no treatment split) is reported as a
prognostic baseline.

Pure numpy/pandas -- no scipy or lifelines needed.

Usage:
  python scripts/biomarker_summary.py
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "workspace"

MIN_ALTERED = 25          # skip gene/cohort pairs with fewer altered patients
TOP_DRUGS = 12            # also test the N most-used individual drugs
CHUNK = 256               # features per vectorised log-rank batch
EXCLUDED_CLASSES = {"Other"}

ALTERATIONS = {
    "mut": "cell2mutation_labeled.txt",
    "amp": "cell2cnamplification_labeled.txt",
    "del": "cell2cndeletion_labeled.txt",
}


# ---------------------------------------------------------------- loading

def load_patient_alterations() -> pd.DataFrame:
    """Patients x features ("KRAS mut", "ERBB2 amp", ...), True if altered in any sample."""
    frames = []
    for kind, name in ALTERATIONS.items():
        m = pd.read_csv(DATA / name, sep="\t", skiprows=1, index_col=0)
        m = m.loc[:, ~m.columns.str.startswith("Unnamed")].astype(bool)
        m.columns = [f"{gene} {kind}" for gene in m.columns]
        frames.append(m)
    samples = pd.concat(frames, axis=1)
    patients = samples.index.str[:9]
    return samples.groupby(patients).any()


def load_lines() -> pd.DataFrame:
    pfs = pd.read_csv(DATA / "pfs_months.txt", sep="\t")
    pfs = pfs[pfs["PFS_MONTHS"].notna() & (pfs["PFS_MONTHS"] >= 0)]
    pfs["event"] = pfs["PFS_STATUS"].astype(str).str.startswith("1")
    return pfs.sort_values("START_DATE")


def load_os() -> pd.DataFrame:
    os_df = pd.read_csv(DATA / "OS_time_adjusted.txt", sep="\t")
    os_df = os_df[os_df["OS_MONTHS"].notna()]
    os_df["event"] = os_df["OS_STATUS"].astype(str).str.startswith("1")
    # One row per patient: the longest follow-up (earliest sample).
    return os_df.sort_values("OS_MONTHS").groupby("PATIENT_ID").tail(1).set_index("PATIENT_ID")


# ---------------------------------------------------------------- statistics

def logrank(time: np.ndarray, event: np.ndarray, groups: np.ndarray) -> dict[str, np.ndarray]:
    """Vectorised log-rank for many binary groupings at once.

    groups is (n_patients, n_features) bool. Returns per-feature observed and
    expected events in the altered group, the variance, and a Peto log-HR.
    """
    order = np.argsort(time, kind="stable")
    t, e, g = time[order], event[order].astype(float), groups[order].astype(float)
    n = len(t)

    uniq, first = np.unique(t, return_index=True)
    at_risk = (n - first).astype(float)                         # (T,)
    deaths = np.add.reduceat(e, first)                           # (T,)

    g_before = np.vstack([np.zeros(g.shape[1]), np.cumsum(g, axis=0)[:-1]])
    at_risk1 = g.sum(axis=0) - g_before[first]                   # (T, F)
    deaths1 = np.add.reduceat(g * e[:, None], first, axis=0)     # (T, F)

    frac = at_risk1 / at_risk[:, None]
    expected1 = (deaths[:, None] * frac).sum(axis=0)
    observed1 = deaths1.sum(axis=0)
    tie = np.where(at_risk > 1, (at_risk - deaths) / np.maximum(at_risk - 1, 1), 0.0)
    var = (deaths[:, None] * frac * (1 - frac) * tie[:, None]).sum(axis=0)

    with np.errstate(divide="ignore", invalid="ignore"):
        log_hr = (observed1 - expected1) / var
        chi2 = (observed1 - expected1) ** 2 / var
    p = np.array([math.erfc(math.sqrt(c / 2)) if np.isfinite(c) else np.nan for c in chi2])
    return {"log_hr": log_hr, "se": 1 / np.sqrt(var), "p": p}


def km_median(time: np.ndarray, event: np.ndarray) -> float:
    """Kaplan-Meier median survival, NaN if the curve never drops to 0.5."""
    if len(time) == 0:
        return float("nan")
    order = np.argsort(time)
    t, e = time[order], event[order]
    uniq, first = np.unique(t, return_index=True)
    at_risk = len(t) - first
    deaths = np.add.reduceat(e.astype(float), first)
    surv = np.cumprod(1 - deaths / at_risk)
    below = np.nonzero(surv <= 0.5)[0]
    return float(uniq[below[0]]) if len(below) else float("nan")


def bh_qvalues(p: np.ndarray) -> np.ndarray:
    q = np.full_like(p, np.nan, dtype=float)
    ok = np.isfinite(p)
    pv = p[ok]
    order = np.argsort(pv)
    ranked = pv[order] * len(pv) / np.arange(1, len(pv) + 1)
    ranked = np.minimum.accumulate(ranked[::-1])[::-1]
    out = np.empty_like(pv)
    out[order] = np.minimum(ranked, 1.0)
    q[ok] = out
    return q


def test_cohort(name: str, kind: str, time, event, alt: pd.DataFrame) -> pd.DataFrame:
    """Log-rank every feature with enough altered patients in this cohort."""
    counts = alt.sum(axis=0)
    keep = counts[(counts >= MIN_ALTERED) & (counts <= len(alt) - MIN_ALTERED)].index
    rows = []
    for start in range(0, len(keep), CHUNK):
        cols = keep[start:start + CHUNK]
        res = logrank(time, event, alt[cols].to_numpy())
        rows.append(pd.DataFrame({
            "cohort": name, "cohort_type": kind, "feature": cols,
            "n_altered": counts[cols].to_numpy(), "n_cohort": len(alt),
            "log_hr": res["log_hr"], "se": res["se"], "p": res["p"],
        }))
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


# ---------------------------------------------------------------- pipeline

def first_lines(lines: pd.DataFrame, key: str, alt_index: pd.Index) -> pd.DataFrame:
    sub = lines[lines["PATIENT_ID"].isin(alt_index)]
    return sub.groupby(["PATIENT_ID", key], sort=False).head(1)


def run() -> tuple[pd.DataFrame, dict]:
    print("Loading genomics...")
    alt = load_patient_alterations()
    lines = load_lines()
    os_df = load_os()

    by_class = first_lines(lines, "DRUG_CLASS", alt.index)
    by_drug = first_lines(lines, "DRUG", alt.index)
    top_drugs = by_drug["DRUG"].value_counts().head(TOP_DRUGS).index

    cohorts = [("class", c, by_class[by_class["DRUG_CLASS"] == c],
                by_class[by_class["DRUG_CLASS"] != c])
               for c in sorted(set(by_class["DRUG_CLASS"]) - EXCLUDED_CLASSES)]
    cohorts += [("drug", d, by_drug[by_drug["DRUG"] == d], by_drug[by_drug["DRUG"] != d])
                for d in top_drugs]

    results = []
    medians: dict[tuple[str, str], tuple[float, float]] = {}
    for kind, name, inside, outside in cohorts:
        print(f"  testing {kind:5s} {name}  (n={len(inside)})")
        res = test_cohort(name, kind, inside["PFS_MONTHS"].to_numpy(),
                          inside["event"].to_numpy(), alt.loc[inside["PATIENT_ID"]])
        if res.empty:
            continue
        # Same features in all other cohorts, one line per patient.
        other = outside.drop_duplicates("PATIENT_ID")
        other_alt = alt.loc[other["PATIENT_ID"], res["feature"]]
        o = logrank(other["PFS_MONTHS"].to_numpy(), other["event"].to_numpy(), other_alt.to_numpy())
        res["log_hr_other"] = o["log_hr"]
        res["se_other"] = o["se"]
        results.append(res)
        medians[(kind, name)] = (inside, alt.loc[inside["PATIENT_ID"]])

    pfs_res = pd.concat(results, ignore_index=True)
    pfs_res["q"] = bh_qvalues(pfs_res["p"].to_numpy())
    z = (pfs_res["log_hr"] - pfs_res["log_hr_other"]) / np.sqrt(pfs_res["se"] ** 2 + pfs_res["se_other"] ** 2)
    pfs_res["p_interaction"] = [math.erfc(abs(v) / math.sqrt(2)) if np.isfinite(v) else np.nan for v in z]
    pfs_res["q_interaction"] = bh_qvalues(pfs_res["p_interaction"].to_numpy())
    pfs_res["hr"] = np.exp(pfs_res["log_hr"])
    pfs_res["hr_other"] = np.exp(pfs_res["log_hr_other"])

    # Medians only for rows that will be shown -- KM per row is the slow part.
    pfs_res["median_pfs_altered"] = np.nan
    pfs_res["median_pfs_unaltered"] = np.nan
    show = pfs_res.index[(pfs_res["q"] < 0.05) | (pfs_res["q_interaction"] < 0.1)]
    for i in show:
        row = pfs_res.loc[i]
        inside, a = medians[(row["cohort_type"], row["cohort"])]
        mask = a[row["feature"]].to_numpy()
        t, e = inside["PFS_MONTHS"].to_numpy(), inside["event"].to_numpy()
        pfs_res.loc[i, "median_pfs_altered"] = km_median(t[mask], e[mask])
        pfs_res.loc[i, "median_pfs_unaltered"] = km_median(t[~mask], e[~mask])

    print("  testing overall survival (all patients)")
    os_pat = os_df.loc[os_df.index.intersection(alt.index)]
    os_res = test_cohort("All patients (OS)", "os", os_pat["OS_MONTHS"].to_numpy(),
                         os_pat["event"].to_numpy(), alt.loc[os_pat.index])
    os_res["q"] = bh_qvalues(os_res["p"].to_numpy())
    os_res["hr"] = np.exp(os_res["log_hr"])

    stats = {
        "patients_genomic": len(alt), "samples": None,
        "patients_treated": by_class["PATIENT_ID"].nunique(),
        "lines": len(lines), "os_patients": len(os_pat),
        "class_counts": by_class["DRUG_CLASS"].value_counts().to_dict(),
        "top_drugs": list(top_drugs),
    }
    return pd.concat([pfs_res, os_res], ignore_index=True), stats


# ---------------------------------------------------------------- report

def _fmt(v: float, digits: int = 2) -> str:
    return "NR" if not np.isfinite(v) else f"{v:.{digits}f}"


def _p(v: float) -> str:
    return "NA" if not np.isfinite(v) else (f"{v:.1e}" if v < 0.001 else f"{v:.3f}")


def _table(df: pd.DataFrame, predictive: bool) -> str:
    head = "| Cohort | Biomarker | n altered / cohort | HR (PFS) | Median PFS altered vs not (mo) | q |"
    sep = "|---|---|---|---|---|---|"
    if predictive:
        head += " HR in other therapies | interaction q |"
        sep += "---|---|"
    out = [head, sep]
    for _, r in df.iterrows():
        line = (f"| {r['cohort']} | {r['feature']} | {int(r['n_altered'])} / {int(r['n_cohort'])} | "
                f"{_fmt(r['hr'])} | {_fmt(r['median_pfs_altered'], 1)} vs {_fmt(r['median_pfs_unaltered'], 1)} | "
                f"{_p(r['q'])} |")
        if predictive:
            line += f" {_fmt(r['hr_other'])} | {_p(r['q_interaction'])} |"
        out.append(line)
    return "\n".join(out)


def write_report(res: pd.DataFrame, stats: dict) -> str:
    pfs = res[res["cohort_type"] != "os"]
    os_res = res[res["cohort_type"] == "os"]

    predictive = (pfs[(pfs["q_interaction"] < 0.1) & (pfs["q"] < 0.1)]
                  .sort_values("p_interaction").head(30))
    strongest = pfs[pfs["q"] < 0.05].sort_values("p").head(25)
    prognostic = os_res[os_res["q"] < 0.05].sort_values("p").head(20)
    class_lines = ", ".join(f"{k} {v}" for k, v in stats["class_counts"].items())

    return f"""# Biomarker x treatment response: pre-computed statistics

Source: MSK-IMPACT-style targeted sequencing (718-gene panel) linked to
treatment lines and survival. Generated by `scripts/biomarker_summary.py`.
Use these numbers as **observational evidence**; confirm mechanisms in the literature.

## Dataset
- Patients with genomic data: {stats['patients_genomic']}; with at least one treatment line: {stats['patients_treated']}; with OS: {stats['os_patients']}
- Treatment lines in file: {stats['lines']}. Patients per drug class (first line of that class): {class_lines}
- Individual drugs also tested: {', '.join(stats['top_drugs'])}
- Alterations per gene: `mut` (mutation), `amp` (copy-number amplification), `del` (deep deletion)

## Method
- Cohort = one drug class or drug; each patient contributes their earliest line in that cohort.
- Altered = alteration present in any of the patient's samples. Only pairs with >= {MIN_ALTERED} altered patients tested.
- Endpoint PFS (months, progression = event). Log-rank test; HR is the Peto estimate (altered vs unaltered).
  **HR > 1 = altered patients progress faster (resistance); HR < 1 = they do better (sensitivity).**
- "HR in other therapies" = same gene's HR across all other cohorts. A low interaction q means the
  effect is specific to this treatment (**predictive**), not just a sicker/healthier subgroup (**prognostic**).
- q = Benjamini-Hochberg FDR across all {len(pfs)} PFS tests. NR = median not reached.

## Important caveats (read before hypothesising)
- **No cancer type in this dataset.** Many genes mark a tumour type (EGFR/lung, APC/colorectal,
  ESR1/breast, AR/prostate), and drugs are chosen by tumour type, so some hits reflect tumour type
  rather than the gene itself. Prefer hits that stay strong vs other therapies and have a mechanism.
- Lines are not randomised; later lines, prior therapies and treatment duration are not adjusted for.
- Alterations are from the panel at any time point, not necessarily before that line of therapy.
- The Peto HR is unreliable far from 1 or in small groups (e.g. an HR above ~5); trust the
  direction and the medians more than the exact size there.

## 1. Candidate predictive biomarkers (effect specific to one treatment)
Sorted by interaction p-value; filtered to q < 0.1 and interaction q < 0.1.

{_table(predictive, predictive=True) if len(predictive) else "_None passed the filter._"}

## 2. Strongest PFS associations overall (may be prognostic or predictive)
{_table(strongest, predictive=True) if len(strongest) else "_None at q < 0.05._"}

## 3. Prognostic baseline: overall survival, all patients
HR > 1 = shorter survival when altered.

| Biomarker | n altered / patients | HR (OS) | q |
|---|---|---|---|
""" + "\n".join(
        f"| {r['feature']} | {int(r['n_altered'])} / {int(r['n_cohort'])} | {_fmt(r['hr'])} | {_p(r['q'])} |"
        for _, r in prognostic.iterrows()
    ) + """

## Full results
Every test (including non-significant ones) is in `biomarker_associations.csv` in this folder.
"""


def main() -> int:
    OUT.mkdir(exist_ok=True)
    res, stats = run()
    cols = ["cohort_type", "cohort", "feature", "n_altered", "n_cohort", "hr", "p", "q",
            "median_pfs_altered", "median_pfs_unaltered", "hr_other", "p_interaction", "q_interaction"]
    res[cols].sort_values("p").to_csv(OUT / "biomarker_associations.csv", index=False)
    report = write_report(res, stats)
    (OUT / "biomarker_summary.md").write_text(report, encoding="utf-8")
    print(f"Wrote {OUT / 'biomarker_summary.md'} ({len(report):,} chars)")
    print(f"Wrote {OUT / 'biomarker_associations.csv'} ({len(res):,} tests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
