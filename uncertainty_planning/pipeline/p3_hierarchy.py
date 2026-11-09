"""P3 - One coherent set of numbers from Finance (total) down to Supply Chain (SKU).

Base forecasts are made for all 53 series (1 total, 5 categories, 17 brands,
30 SKUs), then reconciled so every level adds up. Evaluated 1 month ahead on
2025 with the same rolling origin as the rest of the project.
"""
import _bootstrap  # noqa: F401

import numpy as np
import pandas as pd

from planning import config, io, plots
from planning.data import build_panel
from planning.forecasts import point_forecast, wape
from planning.hierarchy import coherence_gap, reconcile, shrink_covariance, summing_matrix

APPROACH_LABELS = {
    "base": "Base (not coherent)", "bottom_up": "Bottom-up", "top_down": "Top-down (historical shares)",
    "ols": "OLS reconciliation", "wls_structural": "WLS (structural)", "mint_shrink": "MinT (shrinkage)",
}


def base_forecasts(Y: np.ndarray, origin: int, level_of_row: list, method_by_level: dict) -> np.ndarray:
    out = np.empty(Y.shape[0])
    for method in set(method_by_level.values()):
        rows = [r for r, lv in enumerate(level_of_row) if method_by_level[lv] == method]
        out[rows] = point_forecast(Y[rows], origin, 1, method)
    return out


def run() -> dict:
    panel = build_panel()
    S, meta = summing_matrix(panel.attrs, panel.skus)
    Y = S @ panel.X
    levels = meta["level"].tolist()
    cal = panel.idx(config.CALIBRATION_START)
    s0, s1 = panel.idx(config.SELECTION_PERIOD[0]), panel.idx(config.SELECTION_PERIOD[1])
    test = panel.year_idx(config.TEST_YEAR)

    # "Best method per level" is chosen on the selection period only
    selection = {}
    for level in config.HIERARCHY_LEVELS:
        rows = [r for r, lv in enumerate(levels) if lv == level]
        scores = {}
        for m in config.FORECAST_METHODS:
            A = np.column_stack([Y[rows, o] for o in range(s0, s1 + 1)])
            F = np.column_stack([point_forecast(Y[rows], o, 1, m) for o in range(s0, s1 + 1)])
            scores[m] = wape(A, F)
        selection[level] = {"best": min(scores, key=scores.get), "wape": scores}
    method_sets = {
        "historical_average": {lv: "historical_average" for lv in config.HIERARCHY_LEVELS},
        "seasonal_naive": {lv: "seasonal_naive" for lv in config.HIERARCHY_LEVELS},
        "level_best": {lv: selection[lv]["best"] for lv in config.HIERARCHY_LEVELS},
    }

    def evaluate(origins, track_lambda=False):
        rows_out, lambdas = [], []
        for set_name, method_by_level in method_sets.items():
            for t in origins:
                y_hat = base_forecasts(Y, t, levels, method_by_level)
                past = [base_forecasts(Y, o, levels, method_by_level) for o in range(cal, t)]
                residuals = np.vstack([Y[:, o] - f for o, f in zip(range(cal, t), past)])
                if track_lambda and set_name == "level_best":
                    lambdas.append(shrink_covariance(residuals)[1])
                for approach in config.RECONCILIATION_METHODS:
                    y = reconcile(approach, y_hat, S, history_bottom=panel.X[:, :t], residuals=residuals)
                    gap = coherence_gap(y, S)
                    for r in range(len(y)):
                        rows_out.append((set_name, approach, levels[r], meta["series"][r], panel.months[t],
                                         y[r], Y[r, t], gap))
        rec = pd.DataFrame(rows_out, columns=["base_set", "approach", "level", "series", "month",
                                              "forecast", "actual", "coherence_gap"])
        return rec, lambdas

    def level_wape(rec):
        g = rec.assign(abs_err=(rec["actual"] - rec["forecast"]).abs()).groupby(["base_set", "approach", "level"])
        return (g["abs_err"].sum() / g["actual"].sum()).unstack("level")[config.HIERARCHY_LEVELS]

    # The planning default is chosen on the selection period (mean WAPE over the four levels)
    sel_rec, _ = evaluate(range(s0, s1 + 1))
    sel_scores = level_wape(sel_rec).drop(index="base", level="approach").mean(axis=1)
    default_set, default_approach = sel_scores.idxmin()

    rec, lambdas = evaluate(test, track_lambda=True)
    io.save_processed(rec, "reconciled_forecasts")

    acc = (rec.assign(abs_err=(rec["actual"] - rec["forecast"]).abs(), err=rec["forecast"] - rec["actual"])
           .groupby(["base_set", "approach", "level"])
           .agg(abs_err=("abs_err", "sum"), err=("err", "sum"), actual=("actual", "sum"),
                coherence_gap=("coherence_gap", "max"))
           .reset_index())
    acc["wape"] = acc["abs_err"] / acc["actual"]
    acc["bias"] = acc["err"] / acc["actual"]
    acc["coherent"] = acc["coherence_gap"] < 1e-6
    acc = acc.drop(columns=["abs_err", "err", "actual"])
    io.save_table(acc, "p3", "wape_by_level_2025")
    io.save_json(selection, "p3", "level_method_selection")

    plot_df = acc[acc["base_set"] == "level_best"].assign(approach_label=lambda d: d["approach"].map(APPROACH_LABELS))
    plot_df["approach_label"] = pd.Categorical(plot_df["approach_label"], [APPROACH_LABELS[a] for a in config.RECONCILIATION_METHODS])
    sel_methods = {lv: config.METHOD_LABELS[v["best"]].lower() for lv, v in selection.items()}
    note = (f"Base forecasts chosen on Jul-Dec 2024: total {sel_methods['total']}, category {sel_methods['category']}, "
            f"brand {sel_methods['brand']}, SKU {sel_methods['sku']}. Amber = planning default (chosen pre-test). "
            "Base rows do not add up; all others do.")
    plots.hierarchy_wape(plot_df.sort_values("approach_label"), io.figure_path("p3", "01_wape_by_level"),
                         highlight=APPROACH_LABELS[default_approach] if default_set == "level_best" else None, note=note)

    pivot = acc.pivot_table(index=["base_set", "approach"], columns="level", values="wape")[config.HIERARCHY_LEVELS]
    best_coherent = (default_set, default_approach)
    summary = {
        "level_method_selection": {lv: v["best"] for lv, v in selection.items()},
        "wape": {f"{b}|{a}": row.to_dict() for (b, a), row in pivot.iterrows()},
        "selection_scores": {f"{b}|{a}": float(v) for (b, a), v in sel_scores.items()},
        "best_coherent": {"base_set": best_coherent[0], "approach": best_coherent[1],
                          "chosen_on": "selection period (mean WAPE over levels)",
                          **pivot.loc[best_coherent].to_dict()},
        "mint_shrinkage_lambda_mean": float(np.mean(lambdas)),
    }
    io.save_json(summary, "p3", "p3_summary")
    b = summary["best_coherent"]
    print(f"P3  planning default (chosen pre-test): {b['base_set']} + {b['approach']} -> total {b['total']:.3f}, "
          f"category {b['category']:.3f}, brand {b['brand']:.3f}, SKU {b['sku']:.3f}")
    return summary


if __name__ == "__main__":
    run()
