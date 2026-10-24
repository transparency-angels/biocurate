"""Render portable Kaplan-Meier figures from aggregate lifelines estimates."""

from __future__ import annotations

import io
from typing import Any

import numpy as np


def survival_plot_images(report: dict[str, Any]) -> dict[str, bytes]:
    """Return PNGs keyed by their paths relative to summary.md.

    Use an Agg canvas directly so rendering works without a display and does
    not alter the application's global pyplot backend.
    """
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    images = {}
    for curve in report["survival_curves"]:
        candidate = curve["association"]
        figure = Figure(figsize=(11, 8.2), layout="constrained")
        FigureCanvasAgg(figure)
        axes, risk_axes = figure.subplots(2, 1, gridspec_kw={"height_ratios": [4.5, 1]})
        horizon = max(curve[group]["timeline"][-1] for group in ("altered", "unaltered"))
        ticks = np.linspace(0, horizon if horizon > 0 else 1, 6)
        risk_rows = []
        for group, label, color in (("altered", "Altered", "#2563eb"), ("unaltered", "Unaltered", "#ea580c")):
            estimate = curve[group]
            time = np.asarray(estimate["timeline"])
            survival = np.asarray(estimate["survival_probability"])
            count = candidate[f"{group}_samples"]
            events = candidate[f"{group}_events"]
            axes.step(time, survival, where="post", color=color, linewidth=2,
                      label=f"{label} (n={count:,}; events={events:,})")
            axes.fill_between(time, estimate["ci_lower"], estimate["ci_upper"], step="post", color=color, alpha=0.15)
            censored = np.asarray(estimate["censored"]) > 0
            axes.scatter(time[censored], survival[censored], color=color, marker="+", s=15, linewidths=0.8, alpha=0.65)
            removed = np.asarray(estimate["removed"])
            risk_rows.append([str(int(count - removed[time < tick].sum())) for tick in ticks])
        axes.set(
            title=f"{candidate['biomarker']} {candidate['alteration_type']} | {candidate['drug']}",
            xlabel=f"{report['endpoint']['label']} time (months)",
            ylabel="Survival probability", ylim=(-0.02, 1.02), xlim=(0, ticks[-1]), xticks=ticks,
        )
        axes.set_title(axes.get_title(), fontsize=15, fontweight="bold", pad=30)
        axes.text(0.5, 1.025,
                  f"Log-rank p = {candidate['p_value']:.3e}   |   χ² = {candidate['logrank_statistic']:.3f}   |   95% confidence bands; + censored",
                  transform=axes.transAxes, ha="center", fontsize=10)
        axes.grid(alpha=0.2)
        axes.spines[["top", "right"]].set_visible(False)
        axes.legend(frameon=False, loc="best", fontsize=10)
        risk_axes.set_axis_off()
        risk_axes.set_title("Number at risk just before time t (months)", fontsize=10, loc="left")
        table = risk_axes.table(cellText=risk_rows, rowLabels=["Altered", "Unaltered"],
                                colLabels=[f"{tick:.1f}" for tick in ticks], cellLoc="center", loc="center")
        table.auto_set_font_size(False)
        table.set_fontsize(9)
        table.scale(1, 1.5)
        for cell in table.get_celld().values():
            cell.set_edgecolor("#e5e7eb")
        output = io.BytesIO()
        figure.savefig(output, format="png", dpi=160, metadata={"Software": "lifelines KaplanMeierFitter; matplotlib Agg"})
        images[curve["path"]] = output.getvalue()
    return images
