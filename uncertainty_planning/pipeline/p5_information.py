"""P5 - What is better information worth, and do planner overrides add value?

A. Value of information: forecasts that see a share ``p`` of large orders in a
   pipeline, re-calibrated and run through the same inventory policy.
B. Forecast Value Added: four simulated planner archetypes override the
   statistical forecast; accuracy and inventory cost are compared with it.
"""
import _bootstrap  # noqa: F401

import numpy as np
import pandas as pd

from planning import config, io, plots
from planning.data import build_panel
from planning.forecasts import make_forecaster, rolling_point_errors, wape
from planning.information import (archetype_forecaster, fva_summary, override_log, pipeline_forecaster,
                                  visible_large_matrix)
from planning.inventory import add_costs, critical_ratio, quantities, simulate, summarize
from planning.policies import quantile_order_up_to, shifted_point_order_up_to
from planning.uncertainty import QuantileModel


def priced(res, test, attrs, skus):
    q = quantities(res, test)
    q.index = skus
    return summarize(add_costs(q, attrs, config.BASE_HOLDING_RATE, config.BASE_LOST_SALE_BASIS))


def band(series):
    return series.mean(), series.quantile(0.05), series.quantile(0.95)


def run() -> dict:
    panel = build_panel()
    X, attrs = panel.X, panel.attrs.loc[panel.skus]
    cal, start, T = panel.idx(config.CALIBRATION_START), panel.idx(config.SIM_START), panel.n_months
    test = panel.year_idx(config.TEST_YEAR)
    champ = io.load_json("p2", "champion")
    qm_star, fm_star = champ["quantile_method"], champ["forecast_method"]
    L, w = config.BASE_LEAD_TIME, config.BASE_LEAD_TIME + config.REVIEW_PERIOD
    review = list(range(start, T))
    tau_cr = critical_ratio(attrs, config.BASE_HOLDING_RATE, config.BASE_LOST_SALE_BASIS)
    policies = {"cost_optimal": tau_cr, "uniform_95": 0.95}

    # ------------------------------------------------- A. value of information
    voi_rows = []
    for p in config.VISIBILITY_LEVELS:
        seeds = [0] if p in (0.0, 1.0) else range(config.N_SEEDS)
        for s in seeds:
            rng = np.random.default_rng(config.RANDOM_SEED + 1000 * s + int(p * 100))
            visible = visible_large_matrix(panel, p, rng)
            f = pipeline_forecaster(panel, visible, p)
            A, F = rolling_point_errors(X, f, test)
            model = QuantileModel(X, f, w, qm_star, cal)
            for name, tau in policies.items():
                res = simulate(X, quantile_order_up_to(model, tau, review, T), L, start, T)
                voi_rows.append({"visibility": p, "seed": s, "policy": name, "sku_wape_h1": wape(A, F),
                                 "total_wape_h1": wape(A.sum(0), F.sum(0)), **priced(res, test, attrs, panel.skus)})
    voi = pd.DataFrame(voi_rows)
    io.save_table(voi, "p5", "voi_runs")
    agg = voi.groupby(["policy", "visibility"]).agg(
        sku_wape=("sku_wape_h1", "mean"), sku_wape_p05=("sku_wape_h1", lambda s: s.quantile(.05)),
        sku_wape_p95=("sku_wape_h1", lambda s: s.quantile(.95)),
        inventory_value=("avg_inventory_value", "mean"), inventory_p05=("avg_inventory_value", lambda s: s.quantile(.05)),
        inventory_p95=("avg_inventory_value", lambda s: s.quantile(.95)),
        fill_rate=("fill_rate", "mean"), total_cost=("total_cost", "mean"),
        total_cost_p05=("total_cost", lambda s: s.quantile(.05)), total_cost_p95=("total_cost", lambda s: s.quantile(.95)),
        runs=("seed", "count")).reset_index()
    base0 = agg[agg["visibility"] == 0].set_index("policy")
    agg["inventory_reduction_vs_none"] = agg.apply(lambda r: 1 - r["inventory_value"] / base0.loc[r["policy"], "inventory_value"], axis=1)
    agg["cost_saving_vs_none"] = agg.apply(lambda r: base0.loc[r["policy"], "total_cost"] - r["total_cost"], axis=1)
    io.save_table(agg, "p5", "voi_summary")

    g = agg[agg["policy"] == "cost_optimal"].sort_values("visibility")
    x = g["visibility"].to_numpy()
    plots.voi_lines(x, {"Cost-optimal policy": (g["inventory_value"].to_numpy() / 1000, g["inventory_p05"].to_numpy() / 1000,
                                                 g["inventory_p95"].to_numpy() / 1000)},
                    "Average inventory value, $K (at cost)", "Seeing large orders early frees working capital",
                    "Same cost-optimal service targets; buffers re-calibrated on each scenario's own errors",
                    io.figure_path("p5", "01_voi_inventory"), fmt="${:.0f}K")
    plots.voi_lines(x, {"SKU-month WAPE": (100 * g["sku_wape"].to_numpy(), 100 * g["sku_wape_p05"].to_numpy(),
                                           100 * g["sku_wape_p95"].to_numpy())},
                    "WAPE, % (1 month ahead, 2025)", "Information breaks the history-only noise floor",
                    "History alone cannot go below ~26% (main project); pipeline visibility can",
                    io.figure_path("p5", "02_voi_wape"), fmt="{:.1f}%",
                    ref=(26.2, "History-only noise floor, 26.2% (main project)"))

    # ------------------------------------------------ B. Forecast Value Added
    stat = make_forecaster(X, fm_star)
    stat_model = QuantileModel(X, stat, w, qm_star, cal)
    stat_res = simulate(X, quantile_order_up_to(stat_model, tau_cr, review, T), L, start, T)
    stat_cost = priced(stat_res, test, attrs, panel.skus)
    fva_rows, logs = [], []
    for name, params in config.PLANNER_ARCHETYPES.items():
        seeds = range(config.N_SEEDS) if name in ("informed", "optimistic") else [0]
        for s in seeds:
            rng = np.random.default_rng(config.RANDOM_SEED + 7 * s + 1)
            adjusted, _ = archetype_forecaster(name, params, panel, stat, rng)
            log = override_log(name, panel, stat, adjusted, test)
            res = simulate(X, shifted_point_order_up_to(stat_model, adjusted, tau_cr, review, T), L, start, T)
            cost = priced(res, test, attrs, panel.skus)
            fva_rows.append({"archetype": name, "label": params["label"], "seed": s, **fva_summary(log),
                             "avg_inventory_value": cost["avg_inventory_value"], "fill_rate": cost["fill_rate"],
                             "total_cost": cost["total_cost"],
                             "cost_change_vs_statistical": cost["total_cost"] - stat_cost["total_cost"]})
            if s == 0:
                logs.append(log)
    fva = pd.DataFrame(fva_rows)
    io.save_table(fva, "p5", "fva_runs")
    fva_sum = fva.groupby(["archetype", "label"], sort=False).mean(numeric_only=True).drop(columns="seed").reset_index()
    io.save_table(fva_sum, "p5", "fva_summary")
    override = pd.concat(logs, ignore_index=True)
    io.save_processed(override, "override_log")
    io.save_table(override, "p5", "override_log_sample")
    plots.fva_bars(fva_sum["label"].tolist(), fva_sum["fva_points"].tolist(), io.figure_path("p5", "03_fva"))

    co = agg[agg["policy"] == "cost_optimal"].set_index("visibility")
    summary = {
        "voi_cost_optimal": co[["sku_wape", "inventory_value", "fill_rate", "total_cost",
                                "inventory_reduction_vs_none", "cost_saving_vs_none"]].to_dict("index"),
        "statistical_cost": stat_cost,
        "fva": fva_sum.set_index("archetype")[["fva_points", "bias_final", "overrides_improved_share",
                                               "avg_inventory_value", "cost_change_vs_statistical"]].to_dict("index"),
        "large_order_threshold_units": panel.large_threshold,
    }
    io.save_json(summary, "p5", "p5_summary")
    full, half = co.loc[1.0], co.loc[0.5]
    print(f"P5  visibility 50%: WAPE {half['sku_wape']:.3f}, inventory -{half['inventory_reduction_vs_none']:.1%}; "
          f"100%: WAPE {full['sku_wape']:.3f}, inventory -{full['inventory_reduction_vs_none']:.1%}; "
          f"FVA informed {summary['fva']['informed']['fva_points']:+.1f} pts")
    return summary


if __name__ == "__main__":
    run()
