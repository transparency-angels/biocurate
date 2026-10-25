"""The `dataAnalysis` block of a hypothesis: what the session's own data says about it.

Pure mapping from the stored analysis report, the hypothesis's candidate and its
per-sample points. Everything shown is computed from the data; nothing is taken
from the model-written hypothesis text.

For survival candidates it reports a verdict, the effect (KM medians and a Cox
hazard ratio), significance after FDR correction, Kaplan-Meier curves with
Greenwood log-log 95% bands and numbers at risk, caveats with suggested next
checks, and the methods. For exploratory (non-survival) reports it lists the
dataset findings whose columns the hypothesis names, labelled as related rather
than as a test of the hypothesis.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from pathlib import PurePath
from typing import Any

Z_95 = 1.959963984540054
SMALL_GROUP = 20
FEW_EVENTS = 10
HEAVY_CENSORING = 0.5
MAX_RELATED = 3
AT_RISK_TICKS = 5


# ----------------------------- survival curves ----------------------------- #

def kaplan_meier(times: Sequence[float], events: Sequence[int]) -> dict[str, Any]:
    """Product-limit estimate with Greenwood log-log 95% bands.

    Returns `steps` (`t`, `s`, `lower`, `upper`, starting at t=0) and `censored`
    (the times of censored observations).
    """
    rows = sorted(zip(times, events, strict=True))
    n = len(rows)
    steps = [{"t": 0.0, "s": 1.0, "lower": 1.0, "upper": 1.0}]
    censored: list[float] = []
    s, greenwood, i = 1.0, 0.0, 0
    while i < n:
        t = rows[i][0]
        at_risk = n - i
        deaths = cens = 0
        while i < n and rows[i][0] == t:
            if rows[i][1]:
                deaths += 1
            else:
                cens += 1
            i += 1
        censored.extend([float(t)] * cens)
        if deaths == 0:
            continue
        s *= 1 - deaths / at_risk
        if at_risk > deaths:
            greenwood += deaths / (at_risk * (at_risk - deaths))
        lower = upper = s
        if 0 < s < 1:
            log_s = math.log(s)
            half = Z_95 * math.sqrt(greenwood) / abs(log_s)
            lower, upper = s ** math.exp(half), s ** math.exp(-half)
        steps.append({"t": float(t), "s": round(s, 4), "lower": round(lower, 4),
                      "upper": round(upper, 4)})
    return {"steps": steps, "censored": censored}


def _nice_ticks(t_max: float, count: int = AT_RISK_TICKS) -> list[float]:
    if t_max <= 0:
        return [0.0]
    rough = t_max / (count - 1)
    magnitude = 10 ** math.floor(math.log10(rough))
    step = next(m * magnitude for m in (1, 2, 2.5, 5, 10) if m * magnitude >= rough)
    ticks, t = [], 0.0
    while t <= t_max + 1e-9:
        ticks.append(round(t, 6))
        t += step
    return ticks


def _curves_from_points(points: Sequence[Mapping[str, Any]], labels: Mapping[str, str]) -> dict:
    by_group: dict[str, tuple[list[float], list[int]]] = {}
    for p in points:
        if p.get("event") not in (0, 1) or not isinstance(p.get("value"), int | float):
            return {}
        times, events = by_group.setdefault(str(p.get("group")), ([], []))
        times.append(float(p["value"]))
        events.append(int(p["event"]))
    if set(by_group) != {"altered", "unaltered"}:
        return {}
    ticks = _nice_ticks(max(t for times, _ in by_group.values() for t in times))
    curves, at_risk = [], []
    for group in ("altered", "unaltered"):
        times, events = by_group[group]
        km = kaplan_meier(times, events)
        curves.append({"group": group, "label": labels[group], **km})
    for tick in ticks:
        at_risk.append({"t": tick, **{
            g: sum(1 for t in by_group[g][0] if t >= tick) for g in ("altered", "unaltered")
        }})
    return {"curves": curves, "atRisk": at_risk}


def _curves_from_report(curve: Mapping[str, Any], labels: Mapping[str, str]) -> dict:
    """Older reports stored aggregate curves for the top genes, but no event flags."""
    curves, tables = [], {}
    for group in ("altered", "unaltered"):
        c = curve.get(group) or {}
        timeline = list(c.get("timeline") or [])
        surv = list(c.get("survival_probability") or [])
        low, high = list(c.get("ci_lower") or []), list(c.get("ci_upper") or [])
        if not timeline or not (len(timeline) == len(surv) == len(low) == len(high)):
            return {}
        steps = [{"t": float(t), "s": round(float(s), 4), "lower": round(float(lo), 4),
                  "upper": round(float(hi), 4)}
                 for t, s, lo, hi in zip(timeline, surv, low, high, strict=True)]
        cens = list(c.get("censored") or [])
        censored = [float(t) for t, k in zip(timeline, cens, strict=False) for _ in range(int(k))]
        curves.append({"group": group, "label": labels[group], "steps": steps,
                       "censored": censored})
        tables[group] = (timeline, list(c.get("at_risk") or []))
    ticks = _nice_ticks(max(float(t) for timeline, _ in tables.values() for t in timeline))

    def risk(group: str, tick: float) -> int:
        timeline, counts = tables[group]
        for t, n in zip(timeline, counts, strict=False):
            if float(t) >= tick:
                return int(n)
        return 0

    at_risk = [{"t": t, "altered": risk("altered", t), "unaltered": risk("unaltered", t)}
               for t in ticks]
    return {"curves": curves, "atRisk": at_risk}


# ----------------------------- survival verdict ----------------------------- #

def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, int | float) and math.isfinite(v) else None


def _fmt(v: float | None, digits: int = 1) -> str:
    return "not reached" if v is None else f"{v:.{digits}f}"


def _status(p: float | None, q: float | None, alpha: float) -> str:
    if q is not None:
        return "supported" if q <= alpha else ("nominal" if p is not None and p <= alpha
                                               else "not_significant")
    # Reports from before FDR correction: the p-value alone is only nominal evidence.
    return "nominal" if p is not None and p <= alpha else "not_significant"


def _direction(delta: float | None, hr: float | None) -> str:
    if delta is not None and delta != 0:
        return "worse" if delta < 0 else "better"
    if hr is not None and hr != 1:
        return "worse" if hr > 1 else "better"
    return "unclear"


def _caveats(ev: Mapping[str, Any], groups: list[dict], status: str, tests_run: int | None,
             hr: Mapping[str, float | None], has_events: bool) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []

    def add(level: str, text: str, action: str) -> None:
        out.append({"level": level, "text": text, "action": action})

    if status == "nominal":
        add("warning",
            f"Significant only before correcting for the {tests_run or 'many'} comparisons tested "
            "(FDR q above the threshold); it may be a false positive.",
            "Treat it as hypothesis-generating and replicate it in an independent cohort.")
    for g in groups:
        if g["n"] < SMALL_GROUP:
            add("warning", f"Small group: only {g['n']} samples in “{g['label']}”.",
                "Confirm the effect in a larger or independent cohort.")
        if g["events"] is not None and g["events"] < FEW_EVENTS:
            add("warning",
                f"Few events ({g['events']}) in “{g['label']}”, so the estimates are unstable.",
                "Wait for more follow-up or pool cohorts before relying on the effect size.")
        if g["censored"] is not None and g["n"] and g["censored"] / g["n"] > HEAVY_CENSORING:
            pct = round(100 * g["censored"] / g["n"])
            add("info", f"{pct}% of “{g['label']}” are censored (still event-free at last "
                "follow-up).", "Longer follow-up would sharpen the late part of the curve.")
        if g["median"] is None:
            add("info", f"Median survival is not reached in “{g['label']}”, so the difference "
                "in medians is undefined.",
                "Compare with the hazard ratio or a restricted mean survival time instead.")
    if hr.get("hazard_ratio") is None and has_events:
        add("info", "No hazard ratio: the Cox model did not converge, which happens when the "
            "groups barely overlap in time.", "Inspect the curves; the log-rank result stands.")
    low, high = hr.get("hr_ci_lower"), hr.get("hr_ci_upper")
    if low is not None and high is not None and low <= 1 <= high and status == "supported":
        add("warning", "The hazard ratio's 95% interval includes 1 although the log-rank test "
            "is significant; the effect may not be proportional over time.",
            "Check proportional hazards, or compare survival at fixed time points.")
    add("info", "Unadjusted comparison: no covariates such as stage, age or prior lines of "
        "therapy are controlled for.",
        "Fit a multivariable Cox model with the known prognostic factors.")
    add("info", f"Association, not causation: {ev.get('biomarker', 'biomarker')} status was "
        "observed, not assigned.",
        "Test the mechanism experimentally, or in a biomarker-stratified study.")
    return out


def _methods(ev: Mapping[str, Any], report: Mapping[str, Any]) -> list[dict[str, str]]:
    m = report.get("methods") or {}
    sel = report.get("selection") or {}
    endpoint = report.get("endpoint") or {}
    rows = [
        ("Comparison", "Log-rank test (two groups)" if "logrank" in str(
            ev.get("test_method") or m.get("primary_test") or "") else str(
            ev.get("test_method") or m.get("primary_test") or "")),
        ("Survival estimator", "Kaplan-Meier" if "Kaplan" in str(
            ev.get("survival_estimator") or m.get("survival_estimator") or "") else ""),
        ("Effect size", "Difference in median survival; Cox hazard ratio (unadjusted)"),
        ("Endpoint", " · ".join(x for x in (
            str(endpoint.get("label") or ""),
            "/".join(str(endpoint[k]) for k in ("duration_column", "event_column")
                     if endpoint.get(k)),
        ) if x)),
        ("Significance rule", str(m.get("significance_rule") or "")),
        ("Multiple testing", str(m.get("multiple_testing_correction") or "")),
        ("Comparisons tested", str(sel.get("eligible_tests") or "")),
        ("Cohort", str(ev.get("cohort") or "")),
    ]
    software = report.get("software") or {}
    if software:
        rows.append(("Software", ", ".join(f"{k} {v}" for k, v in software.items())))
    for role, info in (report.get("inputs") or {}).items():
        if isinstance(info, Mapping) and info.get("sha256"):
            name = PurePath(str(info.get("path") or role)).name
            rows.append((f"Input: {role}", f"{name} · sha256 {str(info['sha256'])[:12]}…"))
    return [{"label": k, "value": v} for k, v in rows if v]


def _survival(ev: Mapping[str, Any], points: Sequence[Mapping[str, Any]],
              report: Mapping[str, Any]) -> dict[str, Any]:
    methods = report.get("methods") or {}
    alpha = _num(methods.get("alpha")) or 0.05
    p, q = _num(ev.get("p_value")), _num(ev.get("q_value"))
    status = _status(p, q, alpha)
    biomarker = str(ev.get("biomarker") or "Biomarker")
    alteration = str(ev.get("alteration_type") or "alteration")
    drug = ev.get("drug")
    endpoint = report.get("endpoint") or {}
    endpoint_label = str(endpoint.get("label") or "Survival")
    unit = str(endpoint.get("unit") or "months")
    labels = {"altered": f"{biomarker} {alteration}",
              "unaltered": f"No {biomarker} {alteration}"}
    hr = {k: _num(ev.get(k)) for k in ("hazard_ratio", "hr_ci_lower", "hr_ci_upper")}
    delta = _num(ev.get("delta_os_months"))
    med_alt, med_un = _num(ev.get("median_os_altered")), _num(ev.get("median_os_wt"))
    direction = _direction(delta, hr["hazard_ratio"])

    def count(key: str) -> int | None:
        v = ev.get(key)
        return int(v) if isinstance(v, int | float) else None

    groups = [
        {"group": "altered", "label": labels["altered"], "n": count("altered_samples") or 0,
         "events": count("altered_events"), "censored": count("altered_censored"),
         "median": med_alt},
        {"group": "unaltered", "label": labels["unaltered"],
         "n": count("unaltered_samples") or 0, "events": count("unaltered_events"),
         "censored": count("unaltered_censored"), "median": med_un},
    ]
    has_events = bool(points) and all(pt.get("event") in (0, 1) for pt in points)
    plot = _curves_from_points(points, labels) if has_events else {}
    if not plot:
        key = ev.get("candidate_key")
        match = next((c for c in report.get("survival_curves") or []
                      if (c.get("association") or {}).get("candidate_key") == key), None)
        plot = _curves_from_report(match, labels) if match else {}

    on = f" on {drug}" if drug else ""
    medians = f"median {_fmt(med_alt)} vs {_fmt(med_un)} {unit} without it"
    verb = {"worse": "shorter", "better": "longer"}.get(direction)
    headline = (f"{endpoint_label}{on} was {verb} with {labels['altered']}: {medians}."
                if verb else
                f"{endpoint_label}{on} with {labels['altered']}: {medians}; the direction is "
                "unclear.")
    sel = report.get("selection") or {}
    tests_run = sel.get("eligible_tests") if isinstance(sel.get("eligible_tests"), int) else None
    return {
        "kind": "survival",
        "status": status,
        "headline": headline,
        "endpoint": {"label": endpoint_label, "unit": unit},
        "groups": groups,
        "effect": {"medianDifference": delta, "hazardRatio": hr["hazard_ratio"],
                   "hazardRatioLower": hr["hr_ci_lower"], "hazardRatioUpper": hr["hr_ci_upper"],
                   "direction": direction},
        "significance": {"pValue": p, "qValue": q, "alpha": alpha, "testsRun": tests_run},
        "curves": plot.get("curves", []),
        "atRisk": plot.get("atRisk", []),
        "caveats": _caveats(ev, groups, status, tests_run, hr, has_events),
        "methods": _methods(ev, report),
        "relatedFindings": [],
    }


# ----------------------------- exploratory data ----------------------------- #

def _words(name: str) -> str:
    return re.sub(r"[_\W]+", " ", name).strip().lower()


def _related(text: str, report: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Dataset findings whose column names appear in the hypothesis text."""
    hay = f" {_words(text)} "

    def named(*cols: Any) -> bool:
        return any(len(w := _words(str(c))) >= 3 and f" {w} " in hay for c in cols if c)

    found: list[dict[str, Any]] = []
    for t in report.get("group_comparisons") or []:
        if named(t.get("measure"), t.get("group")):
            groups = ", ".join(f"{g.get('name')} median {g.get('median'):.3g} (n={g.get('n')})"
                               for g in t.get("groups") or []
                               if isinstance(g.get("median"), int | float))
            found.append({
                "title": f"{t.get('measure')} by {t.get('group')}",
                "detail": groups, "test": str(t.get("test") or ""),
                "effect": f"{t.get('effect_size_name')} {_num(t.get('effect_size')) or 0:.2f}",
                "pValue": _num(t.get("p_value")), "qValue": _num(t.get("q_value")),
            })
    for c in report.get("correlations") or []:
        if named(c.get("x"), c.get("y")):
            found.append({
                "title": f"{c.get('x')} and {c.get('y')}",
                "detail": f"n = {c.get('n')}", "test": "Spearman rank correlation",
                "effect": f"rho {_num(c.get('rho')) or 0:.2f}",
                "pValue": _num(c.get("p_value")), "qValue": _num(c.get("q_value")),
            })
    found.sort(key=lambda f: (f["qValue"] is None, f["qValue"] or 1.0))
    return found[:MAX_RELATED]


def _not_tested(report: Mapping[str, Any] | None, text: str) -> dict[str, Any]:
    related = _related(text, report) if report else []
    if not report:
        headline = "No dataset was analysed in this session."
    elif related:
        headline = ("The data was not used to test this hypothesis directly, but it contains "
                    "related findings.")
    else:
        headline = "The session's data does not test this hypothesis."
    return {
        "kind": "exploratory" if report else "none", "status": "not_tested",
        "headline": headline, "endpoint": None, "groups": [], "effect": None,
        "significance": None, "curves": [], "atRisk": [],
        "caveats": [{"level": "info", "text": "Related findings are associations between "
                     "columns the hypothesis mentions; they are not a test of its claim.",
                     "action": "Prespecify the outcome and comparison that would test it."}]
        if related else [],
        "methods": [], "relatedFindings": related,
    }


def data_analysis(
    candidate: Mapping[str, Any] | None, points: Sequence[Mapping[str, Any]],
    report: Mapping[str, Any] | None, hypothesis_text: str,
) -> dict[str, Any]:
    """The `dataAnalysis` block; `candidate` is the report entry linked to the hypothesis."""
    if candidate is not None and report is not None:
        return _survival(candidate, points, report)
    return _not_tested(report, hypothesis_text)
