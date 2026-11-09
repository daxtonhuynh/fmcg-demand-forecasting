"""P4 - From forecast to stock: simulate replenishment policies and price them.

Every policy is simulated month by month from Jul 2024 (warm-up) to Dec 2025,
with carry-over stock, a lead time and lost sales. Only 2025 is scored. The
same simulated quantities are then priced under every cost assumption, so the
sensitivity analysis does not re-run the simulation.

Policy families
- quantile: order up to the tau-quantile of protection-period demand, for a
  uniform tau or a per-SKU cost-optimal tau (critical ratio);
- cover: rule of thumb, expected demand + k months of forecast as buffer.
"""
import _bootstrap  # noqa: F401

import numpy as np
import pandas as pd

from planning import config, io, plots
from planning.data import build_panel
from planning.forecasts import make_forecaster
from planning.inventory import add_costs, critical_ratio, quantities, simulate, summarize
from planning.policies import (cover_order_up_to, cr_label, policy_id, quantile_order_up_to,
                               target_label)
from planning.uncertainty import QuantileModel

MONTHLY_FIELDS = ["opening", "receipts", "order_qty", "demand", "sales", "lost", "closing", "order_up_to"]


def monthly_frame(pid: str, res, panel, test: set) -> pd.DataFrame:
    n, m = res.opening.shape
    data = {
        "policy_id": pid,
        "sku": np.repeat(panel.skus, m),
        "month": np.tile([panel.months[t] for t in res.months], n),
        "is_test": np.tile([t in test for t in res.months], n),
    }
    for f in MONTHLY_FIELDS:
        data[f] = getattr(res, f).reshape(-1)
    return pd.DataFrame(data)


def plan_frame(pid, res, S, model_point, tau, lead_time, panel) -> pd.DataFrame:
    T = panel.n_months
    arriving_now = res.in_transit[:, 0] if lead_time >= 1 else 0.0
    on_hand = res.final_on_hand + arriving_now
    still_in_transit = res.in_transit[:, 1:].sum(axis=1) if lead_time > 1 else 0.0
    position = on_hand + still_in_transit
    order = np.maximum(S[:, T] - position, 0.0)
    attrs = panel.attrs.loc[panel.skus]
    plan_month = panel.months[-1] + pd.DateOffset(months=1)
    return pd.DataFrame({
        "policy_id": pid, "sku": panel.skus, "product_name": attrs["product_name"].to_numpy(),
        "category": attrs["category"].to_numpy(), "abc_class": attrs["abc_class"].to_numpy(),
        "plan_month": plan_month, "lead_time_months": lead_time,
        "arrival_month": plan_month + pd.DateOffset(months=lead_time),
        "service_target": np.broadcast_to(tau, (len(panel.skus),)),
        "expected_demand_protection": model_point, "order_up_to": S[:, T],
        "safety_stock": S[:, T] - model_point, "on_hand": on_hand,
        "in_transit": np.broadcast_to(still_in_transit, (len(panel.skus),)),
        "inventory_position": position, "recommended_order": order,
        "order_value_at_cost": order * attrs["unit_cost"].to_numpy(),
    })


def run() -> dict:
    panel = build_panel()
    X, attrs = panel.X, panel.attrs.loc[panel.skus]
    cal, start, T = panel.idx(config.CALIBRATION_START), panel.idx(config.SIM_START), panel.n_months
    test = panel.year_idx(config.TEST_YEAR)
    champ = io.load_json("p2", "champion")
    fm_star, qm_star = champ["forecast_method"], champ["quantile_method"]
    review_months = list(range(start, T + 1))           # includes the plan month (Jan 2026)

    cr = {(h, b): critical_ratio(attrs, h, b) for h in config.HOLDING_RATES for b in config.LOST_SALE_BASES}
    targets = [(target_label(t), t) for t in config.SERVICE_TARGETS]
    targets += [(cr_label(b, h), cr[(h, b)]) for (h, b) in cr]

    policies, qty_rows, monthly, plans = [], [], [], []
    for L in config.LEAD_TIMES:
        w = L + config.REVIEW_PERIOD
        for fm in config.FORECAST_METHODS:
            forecaster = make_forecaster(X, fm)
            for qm in config.QUANTILE_METHODS:
                model = QuantileModel(X, forecaster, w, qm, cal)
                for label, tau in targets:
                    S = quantile_order_up_to(model, tau, review_months, T + 1)
                    res = simulate(X, S, L, start, T)
                    pid = policy_id(L, fm, qm, label)
                    is_cr = label.startswith("cr_")
                    policies.append({
                        "policy_id": pid, "lead_time": L, "family": "quantile", "method": fm, "qmethod": qm,
                        "target_label": label, "target_value": np.nan if is_cr else float(tau),
                        "cr_basis": label[3:label.rindex("_h")] if is_cr else None,
                        "cr_holding_rate": int(label.split("_h")[1]) / 100 if is_cr else np.nan,
                        "cover_months": np.nan,
                    })
                    qty_rows.append(quantities(res, test).assign(policy_id=pid, sku=panel.skus))
                    monthly.append(monthly_frame(pid, res, panel, set(test)))
                    if fm == fm_star:
                        plans.append(plan_frame(pid, res, S, model.point(T), tau, L, panel))
            for k in config.COVER_RULES:
                S = cover_order_up_to(forecaster, L, k, review_months, len(panel.skus), T + 1)
                res = simulate(X, S, L, start, T)
                pid = policy_id(L, fm, "cover", f"k{k:.2f}")
                policies.append({"policy_id": pid, "lead_time": L, "family": "cover", "method": fm,
                                 "qmethod": "cover", "target_label": f"k{k:.2f}", "target_value": np.nan,
                                 "cr_basis": None, "cr_holding_rate": np.nan, "cover_months": k})
                qty_rows.append(quantities(res, test).assign(policy_id=pid, sku=panel.skus))
                monthly.append(monthly_frame(pid, res, panel, set(test)))

    policies = pd.DataFrame(policies)
    qty = pd.concat(qty_rows, ignore_index=True)
    io.save_processed(policies, "inventory_policies")
    io.save_processed(qty, "inventory_sku_quantities")
    io.save_processed(pd.concat(monthly, ignore_index=True), "inventory_monthly")
    plan = pd.concat(plans, ignore_index=True)
    io.save_processed(plan, "replenishment_plan")

    # ------------------------------------------------------- price everything
    attrs_by_sku = attrs
    summary_rows, sku_costed = [], {}
    for h in config.HOLDING_RATES:
        for b in config.LOST_SALE_BASES:
            for pid, g in qty.groupby("policy_id", sort=False):
                costed = add_costs(g.set_index("sku")[list(g.columns.drop(["policy_id", "sku"]))], attrs_by_sku, h, b)
                summary_rows.append({"policy_id": pid, "holding_rate": h, "lost_sale_basis": b, **summarize(costed)})
                if h == config.BASE_HOLDING_RATE and b == config.BASE_LOST_SALE_BASIS:
                    sku_costed[pid] = costed
    psum = pd.DataFrame(summary_rows).merge(policies, on="policy_id")
    io.save_table(psum, "p4", "policy_summary")

    base = psum[(psum["holding_rate"] == config.BASE_HOLDING_RATE) &
                (psum["lost_sale_basis"] == config.BASE_LOST_SALE_BASIS)]
    L0 = config.BASE_LEAD_TIME
    cr_base = cr_label(config.BASE_LOST_SALE_BASIS, config.BASE_HOLDING_RATE)

    # Target vs achieved cycle service level (simulation check of calibration)
    calib = base[(base["family"] == "quantile") & base["target_value"].notna()][
        ["lead_time", "method", "qmethod", "target_value", "cycle_service_level", "fill_rate"]]
    io.save_table(calib, "p4", "target_vs_achieved_service")

    # Decision-based model comparison at the cost-optimal policy
    p2_point = pd.read_csv(config.STAGE_DIRS["p2"] / "tables" / "point_accuracy_2025.csv").set_index("method")
    comp = base[(base["lead_time"] == L0) & (base["target_label"] == cr_base)].copy()
    comp["sku_wape_h1"] = comp["method"].map(p2_point["sku_wape_h1"])
    comp = comp.sort_values("total_cost")
    io.save_table(comp[["method", "qmethod", "sku_wape_h1", "avg_inventory_value", "fill_rate",
                        "cycle_service_level", "holding_cost", "lost_value", "total_cost"]],
                  "p4", "decision_based_comparison")

    # Sensitivity: cost-optimal per-SKU targets vs uniform rules, under every assumption
    sens_rows = []
    for (L, h, b), g in psum[(psum["method"] == fm_star)].groupby(["lead_time", "holding_rate", "lost_sale_basis"]):
        q = g[g["qmethod"] == qm_star]
        uni = q[q["target_value"].notna() & (q["target_value"] >= 0.8)]
        best_uni = uni.loc[uni["total_cost"].idxmin()]
        sl95 = q[q["target_label"] == "sl95"].iloc[0]
        crp = q[q["target_label"] == cr_label(b, h)].iloc[0]
        cov = g[g["family"] == "cover"]
        best_cov = cov.loc[cov["total_cost"].idxmin()]
        sens_rows.append({
            "lead_time": L, "holding_rate": h, "lost_sale_basis": b,
            "cr_total_cost": crp["total_cost"], "cr_inventory_value": crp["avg_inventory_value"],
            "cr_fill_rate": crp["fill_rate"],
            "sl95_total_cost": sl95["total_cost"], "sl95_inventory_value": sl95["avg_inventory_value"],
            "sl95_fill_rate": sl95["fill_rate"],
            "best_uniform_target_hindsight": best_uni["target_value"], "best_uniform_total_cost": best_uni["total_cost"],
            "best_cover_months_hindsight": best_cov["cover_months"], "best_cover_total_cost": best_cov["total_cost"],
            "cr_saving_vs_sl95": 1 - crp["total_cost"] / sl95["total_cost"],
            "cr_saving_vs_best_cover": 1 - crp["total_cost"] / best_cov["total_cost"],
        })
    sens = pd.DataFrame(sens_rows)
    io.save_table(sens, "p4", "sensitivity")

    # Category view of the planning default
    default_pid = policy_id(L0, fm_star, qm_star, cr_base)
    cat = sku_costed[default_pid].join(attrs[["category"]]).groupby("category").agg(
        demand=("demand", "sum"), sales=("sales", "sum"), inventory_value=("inventory_value", "sum"),
        holding_cost=("holding_cost", "sum"), lost_value=("lost_value", "sum"), total_cost=("total_cost", "sum"))
    cat["fill_rate"] = cat["sales"] / cat["demand"]
    io.save_table(cat.reset_index(), "p4", "default_policy_by_category")

    # ----------------------------------------------------------------- figures
    def curve(rows):
        rows = rows[rows["target_value"] >= 0.8].sort_values("target_value")
        return rows["avg_inventory_value"].to_numpy(), rows["fill_rate"].to_numpy()

    bL = base[base["lead_time"] == L0]
    default = bL[bL["policy_id"] == default_pid].iloc[0]
    hl = {"Cost-optimal per SKU": (default["avg_inventory_value"], default["fill_rate"])}
    curves_m = {config.METHOD_LABELS[m]: curve(bL[(bL["method"] == m) & (bL["qmethod"] == qm_star)])
                for m in config.FORECAST_METHODS}
    plots.frontier(curves_m, hl, io.figure_path("p4", "01_frontier_forecast_methods"),
                   "Better forecasts buy service with less stock")
    curves_q = {config.QMETHOD_LABELS[q]: curve(bL[(bL["method"] == fm_star) & (bL["qmethod"] == q)])
                for q in config.QUANTILE_METHODS}
    cov = bL[(bL["method"] == fm_star) & (bL["family"] == "cover")].sort_values("cover_months")
    curves_q["Rule of thumb (k months of cover)"] = (cov["avg_inventory_value"].to_numpy(), cov["fill_rate"].to_numpy())
    plots.frontier(curves_q, hl, io.figure_path("p4", "02_frontier_buffer_methods"),
                   "Safety-stock methods on the same forecast")
    uni = bL[(bL["method"] == fm_star) & (bL["qmethod"] == qm_star) & (bL["target_value"] >= 0.8)].sort_values("target_value")
    best_cover_cost = cov["total_cost"].min()
    plots.cost_curve(uni["target_value"].to_numpy(), {"Uniform target, same for every SKU": uni["total_cost"].to_numpy()},
                     {"Cost-optimal target per SKU": default["total_cost"],
                      "Best rule of thumb (chosen in hindsight)": best_cover_cost},
                     io.figure_path("p4", "03_cost_vs_service"))

    # ---------------------------------------------------------------- summary
    sl95 = bL[bL["policy_id"] == policy_id(L0, fm_star, qm_star, "sl95")].iloc[0]
    monthly_cogs = float((X[:, test] * attrs["unit_cost"].to_numpy()[:, None]).sum(0).mean())
    plan_default = plan[plan["policy_id"] == default_pid]
    summary = {
        "default_policy": default_pid,
        "default": default[["avg_inventory_value", "fill_rate", "cycle_service_level", "holding_cost",
                            "lost_value", "total_cost", "lost_units"]].to_dict(),
        "uniform_95": sl95[["avg_inventory_value", "fill_rate", "cycle_service_level", "holding_cost",
                            "lost_value", "total_cost"]].to_dict(),
        "best_cover_total_cost": float(best_cover_cost),
        "monthly_demand_at_cost": monthly_cogs,
        "inventory_months_of_cogs": float(default["avg_inventory_value"] / monthly_cogs),
        "sensitivity_cr_beats_sl95_share": float((sens["cr_saving_vs_sl95"] > 0).mean()),
        "sensitivity_cr_saving_vs_sl95_range": [float(sens["cr_saving_vs_sl95"].min()), float(sens["cr_saving_vs_sl95"].max())],
        "decision_ranking": comp[["method", "qmethod", "total_cost"]].to_dict("records"),
        "plan_month": plan_default["plan_month"].iloc[0],
        "plan_total_order_value": float(plan_default["order_value_at_cost"].sum()),
        "plan_total_order_units": float(plan_default["recommended_order"].sum()),
        "n_policies": int(len(policies)),
    }
    io.save_json(summary, "p4", "p4_summary")
    d = summary["default"]
    print(f"P4  {len(policies)} policies simulated; default {default_pid}: inventory ${d['avg_inventory_value']:,.0f}, "
          f"fill {d['fill_rate']:.3%}, cost ${d['total_cost']:,.0f}/yr vs uniform 95% ${sl95['total_cost']:,.0f}")
    return summary


if __name__ == "__main__":
    run()
