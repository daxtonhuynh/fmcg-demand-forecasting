"""Value of information (pipeline visibility) and simulated planner overrides (FVA).

Large orders (at or above the pre-test 90th percentile of order size) carry most
of the month-to-month swing. A CRM or order pipeline would reveal some of them
before the replenishment decision. We simulate that: each large order is visible
with probability ``p``, independently, at least ``lead time + 1`` months ahead
(i.e. for the whole protection period). The forecast for a window is then

    expected base demand + visible large orders + (1 - p) * expected large demand

Results are an upper bound on what a real pipeline would deliver: real pipelines
carry win probabilities and date slippage, which this simulation leaves out.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .data import Panel, pivot_units
from .forecasts import Forecaster


def visible_large_matrix(panel: Panel, p: float, rng: np.random.Generator) -> np.ndarray:
    large = panel.extra["large_orders"]
    if p <= 0:
        return np.zeros_like(panel.X)
    if p >= 1:
        return panel.X_large.copy()
    visible = large[rng.random(len(large)) < p]
    return pivot_units(visible, panel.skus, panel.months)


def pipeline_forecaster(panel: Panel, visible: np.ndarray, p: float) -> Forecaster:
    """Historical-average forecaster that adds orders already visible in the pipeline."""
    base, large = panel.X_base, panel.X_large

    def forecast(origin: int, window: int) -> np.ndarray:
        expected_base = window * base[:, :origin].mean(axis=1)
        expected_unseen = (1 - p) * window * large[:, :origin].mean(axis=1)
        known = visible[:, origin:origin + window].sum(axis=1)
        return expected_base + expected_unseen + known

    return forecast


# ------------------------------------------------------------- planner archetypes
def archetype_forecaster(name: str, params: dict, panel: Panel, statistical: Forecaster,
                         rng: np.random.Generator) -> tuple[Forecaster, np.ndarray | None]:
    """Return the planner's adjusted forecaster (and the override mask, if random)."""
    X = panel.X
    if name == "informed":
        visible = visible_large_matrix(panel, params["visibility"], rng)
        return pipeline_forecaster(panel, visible, params["visibility"]), visible
    if name == "optimistic":
        mask = rng.random(X.shape) < params["share"]          # SKU-months the planner "lifts"
        return (lambda o, w: statistical(o, w) * (1 + params["uplift"] * mask[:, o])), mask
    if name == "chaser":
        a = params["weight_last"]
        return (lambda o, w: (1 - a) * statistical(o, w) + a * w * X[:, o - 1]), None
    if name == "sandbagger":
        return (lambda o, w: statistical(o, w) * (1 - params["cut"])), None
    raise ValueError(f"unknown archetype {name!r}")


REASON_CODES = {
    "informed": "Known large order(s) in pipeline",
    "optimistic": "Expected campaign lift",
    "chaser": "Recent sales trend",
    "sandbagger": "Conservative target buffer",
}


def override_log(name: str, panel: Panel, statistical: Forecaster, adjusted: Forecaster,
                 origins: list[int]) -> pd.DataFrame:
    """One row per SKU-month: the statistical forecast, the planner's number and the actual."""
    rows = []
    for t in origins:
        stat, final, actual = statistical(t, 1), adjusted(t, 1), panel.X[:, t]
        for i, sku in enumerate(panel.skus):
            changed = abs(final[i] - stat[i]) > 1e-6
            rows.append({
                "archetype": name, "sku": sku, "month": panel.months[t],
                "statistical_forecast": stat[i], "final_forecast": final[i],
                "overridden": changed, "reason_code": REASON_CODES[name] if changed else "",
                "actual": actual[i],
                "abs_error_statistical": abs(actual[i] - stat[i]),
                "abs_error_final": abs(actual[i] - final[i]),
            })
    return pd.DataFrame(rows)


def fva_summary(log: pd.DataFrame) -> dict:
    """Forecast Value Added: WAPE(statistical) - WAPE(final); positive = override helped."""
    actual = log["actual"].sum()
    wape_stat = log["abs_error_statistical"].sum() / actual
    wape_final = log["abs_error_final"].sum() / actual
    over = log[log["overridden"]]
    improved = (over["abs_error_final"] < over["abs_error_statistical"]).mean() if len(over) else np.nan
    return {
        "wape_statistical": float(wape_stat),
        "wape_final": float(wape_final),
        "fva_points": float(100 * (wape_stat - wape_final)),
        "bias_final": float((log["final_forecast"].sum() - actual) / actual),
        "override_share": float(log["overridden"].mean()),
        "overrides_improved_share": float(improved),
    }
