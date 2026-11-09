"""Static figures in the project's navy-and-neon theme.

Categorical slots were validated for the navy chart surface (#0b0b5e) with the
dataviz palette validator: the first three pass colour-vision-deficiency checks on
all pairs; slots 4-5 sit in the warn band, so every chart with them also carries a
legend and direct labels.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker  # noqa: E402,F401
import numpy as np  # noqa: E402

PAGE = "#000050"
SURFACE = "#0b0b5e"
INK = "#eef0ff"
INK_2 = "#b9bde6"
MUTED = "#8a8fc4"
GRID = "#1d1d73"
BASELINE = "#2e2e85"
SERIES = ["#10a3be", "#bd870d", "#9e71fd", "#fd259a", "#10af52"]   # cyan, amber, violet, magenta, green
POSITIVE, NEGATIVE = "#10a3be", "#fd259a"


def set_theme() -> None:
    plt.rcParams.update({
        "figure.facecolor": PAGE, "axes.facecolor": SURFACE, "savefig.facecolor": PAGE,
        "axes.edgecolor": BASELINE, "axes.labelcolor": INK_2, "axes.titlecolor": INK,
        "xtick.color": MUTED, "ytick.color": MUTED, "text.color": INK,
        "axes.grid": True, "axes.axisbelow": True, "grid.color": GRID, "grid.linewidth": 0.8, "grid.linestyle": "-",
        "axes.spines.top": False, "axes.spines.right": False,
        "font.family": "DejaVu Sans", "font.size": 10, "axes.titlesize": 12, "axes.titleweight": "bold",
        "axes.titlelocation": "left", "legend.frameon": False, "legend.labelcolor": INK_2,
        "lines.linewidth": 2, "lines.solid_capstyle": "round", "lines.markersize": 7,
    })


def _finish(fig, path: Path, note: str | None = None) -> None:
    if note:
        fig.text(0.01, 0.01, note, color=MUTED, fontsize=8, ha="left", va="bottom")
    fig.tight_layout(rect=(0, 0.04 if note else 0, 1, 1))
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150)
    plt.close(fig)


def _subtitle(ax, text: str) -> None:
    ax.text(0, 1.02, text, transform=ax.transAxes, color=INK_2, fontsize=9, va="bottom")


def reliability(curves: dict, path: Path) -> None:
    """curves: label -> (targets, achieved). Diagonal = perfectly calibrated."""
    set_theme()
    fig, ax = plt.subplots(figsize=(7.5, 5.2))
    ax.plot([0, 1], [0, 1], color=MUTED, lw=1, label="Perfect calibration")
    for k, (label, (x, y)) in enumerate(curves.items()):
        ax.plot(x, y, color=SERIES[k], marker="o", mec=SURFACE, mew=2, label=label)
    ax.set_xlim(0, 1.02); ax.set_ylim(0, 1.02)
    ax.set_xlabel("Target quantile (share of months that should fall below)")
    ax.set_ylabel("Achieved share in 2025")
    ax.set_title("Do the intervals mean what they say?", pad=22)
    _subtitle(ax, "SKU-month, 1 month ahead, historical-average forecast · test year 2025")
    ax.legend(loc="upper left")
    _finish(fig, path)


def tail_reliability(curves: dict, path: Path) -> None:
    """Zoom on the upper tail used for safety stock (target 0.80-0.99)."""
    set_theme()
    fig, ax = plt.subplots(figsize=(7.5, 5.2))
    ax.plot([0.78, 1], [0.78, 1], color=MUTED, lw=1, label="Perfect calibration")
    for k, (label, (x, y)) in enumerate(curves.items()):
        x, y = np.asarray(x), np.asarray(y)
        keep = x >= 0.8
        ax.plot(x[keep], y[keep], color=SERIES[k], marker="o", mec=SURFACE, mew=2, label=label)
    ax.set_xlim(0.78, 1.0); ax.set_ylim(0.70, 1.0)
    ax.set_xlabel("Target quantile"); ax.set_ylabel("Achieved share in 2025")
    ax.set_title("Upper tail: the part that sets safety stock", pad=22)
    _subtitle(ax, "Points below the line mean too little stock for the promised service level")
    ax.legend(loc="lower right")
    _finish(fig, path)


def fan_chart(months, history, actual, quantiles: dict, title: str, path: Path) -> None:
    """quantiles: tau -> values over the forecast months."""
    set_theme()
    fig, ax = plt.subplots(figsize=(9, 4.8))
    hm, hv = history
    ax.plot(hm, hv, color=MUTED, lw=1.5, label="History")
    for lo, hi, alpha in [(0.05, 0.95, 0.12), (0.10, 0.90, 0.18), (0.25, 0.75, 0.28)]:
        ax.fill_between(months, quantiles[lo], quantiles[hi], color=SERIES[0], alpha=alpha, lw=0,
                        label=f"{round((hi - lo) * 100)}% interval")
    ax.plot(months, quantiles[0.5], color=SERIES[0], label="Median forecast")
    ax.plot(months, actual, color=SERIES[1], marker="o", mec=SURFACE, mew=2, label="Actual 2025")
    ax.set_ylabel("Units per month")
    ax.set_title(title, pad=22)
    _subtitle(ax, "1-month-ahead quantile forecasts, re-fitted every month on data known at the time")
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v/1000:.0f}K"))
    ax.legend(loc="upper left", ncol=3, fontsize=8)
    _finish(fig, path)


def calibration_monitor(months, curves: dict, lower_limit, target: float, path: Path) -> None:
    """Cumulative share of actuals below the target quantile, with a binomial alarm limit."""
    set_theme()
    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    ax.axhline(target, color=MUTED, lw=1, label=f"Target {target:.0%}")
    ax.plot(months, lower_limit, color=MUTED, lw=1, ls=(0, (4, 3)), label="Alarm limit (5% one-sided)")
    for k, (label, y) in enumerate(curves.items()):
        ax.plot(months, y, color=SERIES[k], marker="o", mec=SURFACE, mew=2, label=label)
    ax.set_ylabel("Cumulative coverage in 2025")
    ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0, decimals=0))
    ax.set_title(f"Calibration monitor for the {target:.0%} quantile", pad=22)
    _subtitle(ax, "A method falling below the alarm limit is under-covering by more than sampling noise explains")
    ax.legend(loc="lower left", fontsize=8, ncol=2)
    _finish(fig, path)


def hierarchy_wape(table, path: Path, highlight: str | None = None, note: str | None = None) -> None:
    """table: DataFrame with columns level, approach_label, wape (one base-forecast set)."""
    set_theme()
    levels = ["total", "category", "brand", "sku"]
    names = {"total": "Total", "category": "Category", "brand": "Brand", "sku": "SKU"}
    fig, axes = plt.subplots(1, 4, figsize=(12, 4.8), sharey=True)
    approaches = list(dict.fromkeys(table["approach_label"]))
    for ax, level in zip(axes, levels):
        ax.set_axisbelow(True)
        d = table[table["level"] == level].set_index("approach_label").reindex(approaches)
        y = np.arange(len(approaches))
        colors = [SERIES[1] if a == highlight else SERIES[0] for a in approaches]
        ax.barh(y, d["wape"] * 100, height=0.55, color=colors)
        for yi, v in zip(y, d["wape"] * 100):
            ax.text(v, yi, f" {v:.1f}%", va="center", color=INK_2, fontsize=8)
        ax.set_title(names[level], fontsize=11)
        ax.set_xlim(0, d["wape"].max() * 100 * 1.35)
        ax.grid(axis="y", visible=False)
        ax.set_xlabel("WAPE, %")
    axes[0].set_yticks(range(len(approaches)), approaches)
    axes[0].invert_yaxis()
    fig.suptitle("Accuracy at every level after reconciliation (1 month ahead, 2025)",
                 x=0.01, ha="left", color=INK, fontweight="bold")
    _finish(fig, path, note or "Base = each level forecast on its own (numbers do not add up). All other rows add up exactly.")


def frontier(curves: dict, highlight: dict, path: Path, title: str) -> None:
    """curves: label -> (inventory_value, fill_rate) across service targets."""
    set_theme()
    fig, ax = plt.subplots(figsize=(8.5, 5.4))
    for k, (label, (x, y)) in enumerate(curves.items()):
        ax.plot(np.asarray(x) / 1000, np.asarray(y) * 100, color=SERIES[k], marker="o", mec=SURFACE,
                mew=2, label=label)
    for label, (x, y) in highlight.items():
        ax.scatter([x / 1000], [y * 100], s=140, facecolor="none", edgecolor=INK, lw=1.5, zorder=4)
        ax.annotate(label, (x / 1000, y * 100), xytext=(16, -26), textcoords="offset points",
                    color=INK, fontsize=9, arrowprops={"arrowstyle": "-", "color": INK_2, "lw": 0.8})
    ax.set_xlabel("Average inventory value, $K (at cost)")
    ax.set_ylabel("Fill rate, % of demand served")
    ax.set_title(title, pad=22)
    _subtitle(ax, "Each point is a service-level target; up and to the left is better · 2025 simulation")
    ax.legend(loc="lower right")
    _finish(fig, path)


def cost_curve(x, curves: dict, refs: dict, path: Path) -> None:
    """Total cost vs uniform service target; refs: label -> horizontal reference cost."""
    set_theme()
    fig, ax = plt.subplots(figsize=(8.5, 5))
    for k, (label, y) in enumerate(curves.items()):
        ax.plot(np.asarray(x) * 100, np.asarray(y) / 1000, color=SERIES[k], marker="o", mec=SURFACE,
                mew=2, label=label)
    for k, (label, v) in enumerate(refs.items()):
        ax.axhline(v / 1000, color=SERIES[2 + k], lw=1.5, ls=(0, (1, 0)), label=label)
    ymax = max(max(np.asarray(v).max() for v in curves.values()), max(refs.values())) / 1000
    ymin = min(min(np.asarray(v).min() for v in curves.values()), min(refs.values())) / 1000
    ax.set_ylim(ymin - 0.05 * (ymax - ymin), ymax + 0.45 * (ymax - ymin))
    ax.set_xlabel("Uniform service-level target, %")
    ax.set_ylabel("Holding cost + lost profit, $K per year")
    ax.set_title("What a service level costs", pad=22)
    _subtitle(ax, "Holding 25%/yr of unit cost · lost sale = lost profit · lead time 1 month")
    ax.legend(loc="upper center")
    _finish(fig, path)


def voi_lines(x, series: dict, ylabel: str, title: str, subtitle: str, path: Path, fmt="{:.0f}", ref=None) -> None:
    """series: label -> (mean, lo, hi) arrays across visibility levels."""
    set_theme()
    fig, ax = plt.subplots(figsize=(7.5, 4.8))
    for k, (label, (m, lo, hi)) in enumerate(series.items()):
        xs = np.asarray(x) * 100
        ax.fill_between(xs, lo, hi, color=SERIES[k], alpha=0.12, lw=0)
        ax.plot(xs, m, color=SERIES[k], marker="o", mec=SURFACE, mew=2, label=label)
        ax.annotate(fmt.format(m[-1]), (xs[-1], m[-1]), xytext=(6, 0), textcoords="offset points",
                    color=INK_2, va="center", fontsize=9)
    if ref is not None:
        ax.axhline(ref[0], color=MUTED, lw=1, ls=(0, (4, 3)))
        ax.text(1, ref[0], f"{ref[1]} ", transform=ax.get_yaxis_transform(), ha="right", va="bottom",
                color=INK_2, fontsize=9)
    ax.set_xlabel("Share of large orders visible in the pipeline, %")
    ax.set_ylabel(ylabel)
    ax.set_title(title, pad=22)
    _subtitle(ax, subtitle)
    if len(series) > 1:
        ax.legend(loc="upper right")
    _finish(fig, path, "Upper bound: visible orders are assumed certain and on time. Band: 5th-95th percentile over 30 random draws.")


def fva_bars(labels, values, path: Path) -> None:
    set_theme()
    fig, ax = plt.subplots(figsize=(10, 4.4))
    y = np.arange(len(labels))
    colors = [POSITIVE if v >= 0 else NEGATIVE for v in values]
    ax.barh(y, values, height=0.5, color=colors)
    for yi, v in zip(y, values):
        ax.text(v, yi, f" {v:+.1f} pts " if v >= 0 else f" {v:+.1f} pts ", va="center",
                ha="left" if v >= 0 else "right", color=INK, fontsize=9)
    ax.axvline(0, color=BASELINE, lw=1)
    ax.set_yticks(y, labels)
    ax.invert_yaxis()
    lim = max(abs(np.asarray(values))) * 1.6
    ax.set_xlim(-lim, lim)
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("Forecast Value Added, WAPE points (positive = override helped)")
    ax.set_title("Which planner overrides add value?", pad=22)
    _subtitle(ax, "Simulated planners · 2025 · mean of 30 random draws")
    _finish(fig, path)
