"""P7 - Write dashboard/data.js for the Inventory Planning dashboard.

The dashboard prices simulated quantities in the browser, so every holding-rate,
lost-sale and category choice is computed from the same numbers the warehouse
holds (no second model in JavaScript).
"""
import _bootstrap  # noqa: F401

import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from planning import config, io
from planning.inventory import critical_ratio


def r(x, d=4):
    if isinstance(x, (list, tuple, np.ndarray)):
        return [r(v, d) for v in x]
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return None
    return round(float(x), d)


def run() -> dict:
    champ = io.load_json("p2", "champion")
    fm, qm = champ["forecast_method"], champ["quantile_method"]
    p2, p3, p4, p5, p6 = (io.load_json(s, f"{s}_summary") for s in ["p2", "p3", "p4", "p5", "p6"])
    p1 = io.load_json("p1", "p1_summary")
    attrs = io.load_processed("sku_attributes").sort_values("sku")
    skus = attrs["sku"].tolist()
    demand = io.load_processed("demand_panel")
    months = sorted(demand["month"].unique())
    dem = demand.pivot(index="sku", columns="month", values="units").loc[skus]

    # ---- forecast uncertainty
    q = io.load_processed("quantile_forecasts")
    q1 = q[(q["method"] == fm) & (q["window"] == 1)]
    fan = {}
    for qmethod, g in q1.groupby("qmethod"):
        fan[qmethod] = {}
        for sku, gs in g.groupby("sku"):
            w = gs.pivot(index="origin_month", columns="tau", values="quantile")
            fan[qmethod][sku] = {str(t): r(w[t].to_numpy(), 1) for t in config.FAN_TAUS}
    stat_point = {sku: r(gs.sort_values("origin_month").drop_duplicates("origin_month")["forecast"].to_numpy(), 1)
                  for sku, gs in q1[q1["qmethod"] == qm].groupby("sku")}
    test_months = sorted(q1["origin_month"].unique())
    reliability = {}
    for qmethod, g in q1.groupby("qmethod"):
        cov = g.assign(hit=g["actual"] <= g["quantile"]).groupby("tau")["hit"].mean()
        reliability[qmethod] = {"tau": r(cov.index.to_numpy()), "coverage": r(cov.to_numpy())}
    mon = pd.read_csv(config.STAGE_DIRS["p2"] / "tables" / "calibration_monitor_2025.csv")
    monitor = {k: {"coverage": r(g["coverage"].to_numpy()), "limit": r(g["alarm_limit"].to_numpy()),
                   "alarm": g["alarm"].astype(bool).tolist()} for k, g in mon.groupby("qmethod")}
    im = pd.read_csv(config.STAGE_DIRS["p2"] / "tables" / "interval_metrics_2025.csv")
    interval_table = im[im["method"] == fm][["qmethod", "window", "coverage_0.9", "coverage_0.95", "interval90_coverage",
                                             "interval90_rel_width", "scaled_pinball"]].round(4).to_dict("records")
    point_acc = pd.read_csv(config.STAGE_DIRS["p2"] / "tables" / "point_accuracy_2025.csv").round(4).to_dict("records")

    # ---- hierarchy
    h = pd.read_csv(config.STAGE_DIRS["p3"] / "tables" / "wape_by_level_2025.csv")
    hierarchy = h[["base_set", "approach", "level", "wape", "bias", "coherent"]].round(4).to_dict("records")

    # ---- inventory
    pol = io.load_processed("inventory_policies")
    qty = io.load_processed("inventory_sku_quantities")
    fields = ["demand", "sales", "lost", "stockout_months", "avg_on_hand", "months"]
    qty_map = {}
    for pid, g in qty.groupby("policy_id", sort=False):
        g = g.set_index("sku").loc[skus]
        qty_map[pid] = [r(row, 2) for row in g[fields].to_numpy().tolist()]
    cr = {}
    a_idx = attrs.set_index("sku")
    for hr in config.HOLDING_RATES:
        for b in config.LOST_SALE_BASES:
            cr[f"{b}|{hr}"] = r(critical_ratio(a_idx, hr, b), 4)
    plan = io.load_processed("replenishment_plan")
    plan_rows = {}
    for pid, g in plan.groupby("policy_id", sort=False):
        g = g.set_index("sku").loc[skus]
        plan_rows[pid] = [r(row, 1) for row in g[["expected_demand_protection", "safety_stock", "order_up_to",
                                                    "inventory_position", "recommended_order",
                                                    "order_value_at_cost"]].to_numpy().tolist()]
    sens = pd.read_csv(config.STAGE_DIRS["p4"] / "tables" / "sensitivity.csv").round(4).to_dict("records")

    # ---- information
    voi = pd.read_csv(config.STAGE_DIRS["p5"] / "tables" / "voi_summary.csv").round(4).to_dict("records")
    fva = pd.read_csv(config.STAGE_DIRS["p5"] / "tables" / "fva_summary.csv").round(4).to_dict("records")

    data = {
        "meta": {
            "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "test_year": config.TEST_YEAR, "champion_method": fm, "champion_qmethod": qm,
            "default_policy": p4["default_policy"], "plan_month": str(p4["plan_month"])[:7],
            "base_lead_time": config.BASE_LEAD_TIME, "base_holding_rate": config.BASE_HOLDING_RATE,
            "base_basis": config.BASE_LOST_SALE_BASIS, "lead_times": config.LEAD_TIMES,
            "holding_rates": config.HOLDING_RATES, "bases": config.LOST_SALE_BASES,
            "service_targets": [t for t in config.SERVICE_TARGETS if t >= 0.8], "cover_rules": config.COVER_RULES,
            "methods": config.FORECAST_METHODS, "qmethods": config.QUANTILE_METHODS,
            "method_labels": config.METHOD_LABELS, "qmethod_labels": config.QMETHOD_LABELS,
            "large_threshold": p1["large_order_threshold_units"], "large_share_units": p1["large_order_share_of_units"],
            "large_share_orders": p1["large_order_share_of_orders"],
            "large_b2b_share": p1["large_orders_b2b_share"], "monthly_demand_at_cost": p4["monthly_demand_at_cost"],
            "sku_wape": p2["sku_wape_h1"], "total_wape": p2["total_wape_h1"],
            "monitor_first_alarm": p2["monitor_first_alarm"], "hierarchy_default": p3["best_coherent"],
            "checks": f"{p6['checks_passed']}/{p6['checks_total']}",
            "reconciled": f"{p6['reconciled_matching']}/{p6['reconciled_figures']}",
            "n_policies": p4["n_policies"],
        },
        "skus": [{"sku": s, "name": a_idx.loc[s, "product_name"], "category": a_idx.loc[s, "category"],
                  "brand": a_idx.loc[s, "brand"], "abc": a_idx.loc[s, "abc_class"],
                  "unit_cost": r(a_idx.loc[s, "unit_cost"]), "unit_profit": r(a_idx.loc[s, "unit_profit"]),
                  "unit_gross_margin": r(a_idx.loc[s, "unit_gross_margin"])} for s in skus],
        "months": [pd.Timestamp(m).strftime("%Y-%m") for m in months],
        "test_months": [pd.Timestamp(m).strftime("%Y-%m") for m in test_months],
        "demand": {s: r(dem.loc[s].to_numpy(), 0) for s in skus},
        "fan": fan, "stat_point": stat_point, "reliability": reliability, "monitor": monitor,
        "interval_table": interval_table, "point_accuracy": point_acc, "hierarchy": hierarchy,
        "policies": pol[["policy_id", "lead_time", "family", "method", "qmethod", "target_label", "target_value",
                         "cover_months"]].replace({np.nan: None}).to_dict("records"),
        "qty_fields": fields, "qty": qty_map, "critical_ratio": cr,
        "plan_fields": ["expected_demand", "safety_stock", "order_up_to", "inventory_position",
                        "recommended_order", "order_value_at_cost"],
        "plan": plan_rows, "sensitivity": sens, "voi": voi, "fva": fva,
    }
    config.DASHBOARD_DIR.mkdir(parents=True, exist_ok=True)
    js = "// Generated by pipeline/p7_dashboard_data.py - do not edit by hand.\nwindow.PLANNING_DATA = " + \
         json.dumps(data, separators=(",", ":"), default=str) + ";\n"
    path = config.DASHBOARD_DIR / "data.js"
    path.write_text(js)
    print(f"P7  dashboard/data.js written ({path.stat().st_size / 1e6:.2f} MB, {len(qty_map)} policies)")
    return {"bytes": path.stat().st_size}


if __name__ == "__main__":
    run()
