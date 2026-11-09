"""P1 - Demand panel, unit economics and large-order split.

Reads the raw orders (read-only), builds the SKU x month demand panel, checks it
reconciles with the raw file, and records the facts every later stage relies on.
"""
import _bootstrap  # noqa: F401

import numpy as np
import pandas as pd

from planning import config, io
from planning.data import build_panel, load_orders, panel_long
from planning.inventory import critical_ratio


def run() -> dict:
    orders = load_orders()
    panel = build_panel(orders)
    long = panel_long(panel)

    checks = {
        "panel_units_equal_raw_units": bool(np.isclose(long["units"].sum(), orders["Units_Sold"].sum())),
        "large_plus_base_equal_total": bool(np.allclose(long["large_units"] + long["base_units"], long["units"])),
        "no_empty_sku_months": bool((long["units"] > 0).all()),
        "months_gap_free": len(panel.months) == len(pd.date_range(panel.months[0], panel.months[-1], freq="MS")),
    }
    if not all(checks.values()):
        raise RuntimeError(f"P1 checks failed: {checks}")

    attrs = panel.attrs.copy()
    attrs["critical_ratio_base"] = critical_ratio(attrs, config.BASE_HOLDING_RATE, config.BASE_LOST_SALE_BASIS)
    large = panel.extra["large_orders"]
    summary = {
        "raw_file": config.raw_csv_path().name,
        "orders": len(orders),
        "skus": len(panel.skus),
        "months": len(panel.months),
        "first_month": panel.months[0],
        "last_month": panel.months[-1],
        "total_units": float(long["units"].sum()),
        "large_order_threshold_units": panel.large_threshold,
        "large_orders": int(len(large)),
        "large_order_share_of_orders": float(len(large) / len(orders)),
        "large_order_share_of_units": float(large["Units_Sold"].sum() / orders["Units_Sold"].sum()),
        "large_orders_b2b_share": float((large["Customer_Type"] == "B2B").mean()),
        "median_unit_cost": float(attrs["unit_cost"].median()),
        "median_unit_profit": float(attrs["unit_profit"].median()),
        "critical_ratio_base_min": float(attrs["critical_ratio_base"].min()),
        "critical_ratio_base_median": float(attrs["critical_ratio_base"].median()),
        "critical_ratio_base_max": float(attrs["critical_ratio_base"].max()),
        "checks": checks,
    }
    io.save_processed(long, "demand_panel")
    io.save_processed(attrs.reset_index().rename(columns={"SKU": "sku"}), "sku_attributes")
    io.save_table(attrs.reset_index().rename(columns={"SKU": "sku"}), "p1", "sku_attributes")
    io.save_json(summary, "p1", "p1_summary")
    print(f"P1  panel {summary['skus']} SKUs x {summary['months']} months, "
          f"large orders = {summary['large_order_share_of_units']:.1%} of units, checks pass")
    return summary


if __name__ == "__main__":
    run()
