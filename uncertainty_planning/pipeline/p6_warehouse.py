"""P6 - Planning warehouse in DuckDB: load, check, query, reconcile with Python.

Builds ``data/warehouse/planning.duckdb`` (separate from the main project's
warehouse), runs the data-quality checks (the pipeline stops on any failure),
answers the planning questions in SQL and confirms every reconciled figure
matches the Python result.
"""
import _bootstrap  # noqa: F401

import re

import duckdb
import numpy as np
import pandas as pd

from planning import config, io
from planning.policies import cr_label


def month_key(s) -> pd.Series:
    s = pd.to_datetime(pd.Series(s))
    return (s.dt.year * 100 + s.dt.month).astype(int)


def load(con) -> None:
    attrs = io.load_processed("sku_attributes").sort_values("sku").reset_index(drop=True)
    attrs["sku_key"] = np.arange(1, len(attrs) + 1)
    sku_key = dict(zip(attrs["sku"], attrs["sku_key"]))
    demand = io.load_processed("demand_panel")
    months = pd.DataFrame({"month": sorted(demand["month"].unique())})
    months["month_key"] = month_key(months["month"])
    months["year"] = months["month"].dt.year
    months["month_of_year"] = months["month"].dt.month
    months["is_test"] = months["year"] == config.TEST_YEAR

    dims = {
        "dim_sku": attrs[["sku_key", "sku", "product_name", "brand", "category", "abc_class", "unit_price",
                          "unit_cost", "unit_profit", "unit_gross_margin", "critical_ratio_base"]],
        "dim_month": months[["month_key", "month", "year", "month_of_year", "is_test"]],
        "dim_policy": io.load_processed("inventory_policies")[[
            "policy_id", "lead_time", "family", "method", "qmethod", "target_label", "target_value",
            "cr_basis", "cr_holding_rate", "cover_months"]],
    }
    facts = {}
    facts["fact_demand"] = demand.assign(sku_key=demand["sku"].map(sku_key), month_key=month_key(demand["month"]))[
        ["sku_key", "month_key", "units", "large_units", "base_units"]]
    q = io.load_processed("quantile_forecasts")
    facts["fact_quantile_forecast"] = pd.DataFrame({
        "sku_key": q["sku"].map(sku_key), "origin_month_key": month_key(q["origin_month"]),
        "window_months": q["window"], "method": q["method"], "qmethod": q["qmethod"], "tau": q["tau"],
        "quantile_units": q["quantile"], "point_units": q["forecast"], "actual_units": q["actual"]})
    r = io.load_processed("reconciled_forecasts")
    facts["fact_reconciled_forecast"] = pd.DataFrame({
        "base_set": r["base_set"], "approach": r["approach"], "level": r["level"], "series": r["series"],
        "month_key": month_key(r["month"]), "forecast_units": r["forecast"], "actual_units": r["actual"]})
    s = io.load_processed("inventory_monthly")
    facts["fact_inventory_sim"] = s.assign(sku_key=s["sku"].map(sku_key), month_key=month_key(s["month"]))[
        ["policy_id", "sku_key", "month_key", "is_test", "opening", "receipts", "order_qty", "demand", "sales",
         "lost", "closing", "order_up_to"]]
    p = io.load_processed("replenishment_plan")
    facts["fact_replenishment_plan"] = p.assign(sku_key=p["sku"].map(sku_key))[
        ["policy_id", "sku_key", "plan_month", "arrival_month", "lead_time_months", "service_target",
         "expected_demand_protection", "order_up_to", "safety_stock", "on_hand", "in_transit",
         "inventory_position", "recommended_order", "order_value_at_cost"]]
    o = io.load_processed("override_log")
    facts["fact_override_log"] = pd.DataFrame({
        "archetype": o["archetype"], "sku_key": o["sku"].map(sku_key), "month_key": month_key(o["month"]),
        "statistical_forecast": o["statistical_forecast"], "final_forecast": o["final_forecast"],
        "overridden": o["overridden"], "reason_code": o["reason_code"].replace("", None),
        "actual_units": o["actual"]})
    v = pd.read_csv(config.STAGE_DIRS["p5"] / "tables" / "voi_runs.csv")
    facts["fact_voi_run"] = v.rename(columns={"sku_wape_h1": "sku_wape", "total_wape_h1": "total_wape"})[
        ["visibility", "seed", "policy", "sku_wape", "total_wape", "avg_inventory_value", "fill_rate", "total_cost"]]

    for name, df in {**dims, **facts}.items():
        con.register("_df", df)
        con.execute(f"INSERT INTO {name} SELECT * FROM _df")
        con.unregister("_df")


def split_queries(text: str) -> dict:
    blocks = re.split(r"^-- name: ", text, flags=re.M)[1:]
    out = {}
    for b in blocks:
        name, body = b.split("\n", 1)
        out[name.strip()] = body.strip().rstrip(";")
    return out


def reconcile(results: dict, champ: dict) -> pd.DataFrame:
    rows = []

    def add(figure, py, sql):
        rows.append({"figure": figure, "python": float(py), "sql": float(sql), "abs_diff": abs(float(py) - float(sql))})

    m = pd.read_csv(config.STAGE_DIRS["p2"] / "tables" / "interval_metrics_2025.csv")
    m = m[(m["method"] == champ["forecast_method"]) & (m["window"] == 1)].set_index("qmethod")
    for _, row in results["q1_interval_calibration"].iterrows():
        add(f"coverage | {row['qmethod']} | tau {row['tau']:g}", m.loc[row["qmethod"], f"coverage_{row['tau']:g}"],
            row["achieved_coverage"])

    w = pd.read_csv(config.STAGE_DIRS["p3"] / "tables" / "wape_by_level_2025.csv").set_index(["base_set", "approach", "level"])
    for _, row in results["q3_hierarchy_accuracy"].iterrows():
        add(f"WAPE | {row['base_set']} | {row['approach']} | {row['level']}",
            w.loc[(row["base_set"], row["approach"], row["level"]), "wape"], row["wape"])

    ps = pd.read_csv(config.STAGE_DIRS["p4"] / "tables" / "policy_summary.csv")
    ps = ps[(ps["holding_rate"] == config.BASE_HOLDING_RATE) & (ps["lost_sale_basis"] == config.BASE_LOST_SALE_BASIS)]
    ps = ps.set_index("policy_id")
    for _, row in results["q4_policy_frontier"].iterrows():
        for col in ["fill_rate", "cycle_service_level", "avg_inventory_value", "total_cost"]:
            add(f"{col} | {row['policy_id']}", ps.loc[row["policy_id"], col], row[col])

    vs = pd.read_csv(config.STAGE_DIRS["p5"] / "tables" / "voi_summary.csv").set_index(["policy", "visibility"])
    for _, row in results["q8_value_of_information"].iterrows():
        for py_col, sql_col in [("inventory_value", "inventory_value"), ("sku_wape", "sku_wape"), ("total_cost", "total_cost")]:
            add(f"VOI {sql_col} | {row['policy']} | p={row['visibility']:g}",
                vs.loc[(row["policy"], row["visibility"]), py_col], row[sql_col])

    fr = pd.read_csv(config.STAGE_DIRS["p5"] / "tables" / "fva_runs.csv")
    fr = fr[fr["seed"] == 0].set_index("archetype")
    for _, row in results["q9_forecast_value_added"].iterrows():
        add(f"FVA points | {row['archetype']} (draw 0)", fr.loc[row["archetype"], "fva_points"], row["fva_points"])

    out = pd.DataFrame(rows)
    scale = np.maximum(1.0, out[["python", "sql"]].abs().max(axis=1))
    out["match"] = out["abs_diff"] <= 1e-9 * scale
    return out


def run() -> dict:
    config.WAREHOUSE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if config.WAREHOUSE_PATH.exists():
        config.WAREHOUSE_PATH.unlink()          # the warehouse is fully generated; rebuild it
    champ = io.load_json("p2", "champion")
    p4 = io.load_json("p4", "p4_summary")
    sim_months = len(pd.date_range(config.SIM_START, f"{config.TEST_YEAR}-12-01", freq="MS"))
    params = {
        "raw_csv": str(config.raw_csv_path()).replace("'", "''"), "sim_months": sim_months,
        "champion_method": champ["forecast_method"], "champion_qmethod": champ["quantile_method"],
        "default_policy": p4["default_policy"], "holding_rate": config.BASE_HOLDING_RATE,
        "lost_col": {"profit": "unit_profit", "gross_margin": "unit_gross_margin"}[config.BASE_LOST_SALE_BASIS],
        "base_lead": config.BASE_LEAD_TIME, "cr_label": cr_label(config.BASE_LOST_SALE_BASIS, config.BASE_HOLDING_RATE),
    }

    con = duckdb.connect(str(config.WAREHOUSE_PATH))
    con.execute((config.SQL_DIR / "schema.sql").read_text())
    load(con)

    checks = con.execute((config.SQL_DIR / "checks.sql").read_text().format(**params)).df()
    io.save_table(checks, "p6", "data_quality_checks")
    failed = checks[checks["failed_rows"] != 0]
    if len(failed):
        raise RuntimeError(f"Warehouse checks failed:\n{failed}")

    results = {}
    for name, sql in split_queries((config.SQL_DIR / "planning_queries.sql").read_text()).items():
        results[name] = con.execute(sql.format(**params)).df()
        io.save_table(results[name], "p6", name)
    rec = reconcile(results, champ)
    io.save_table(rec, "p6", "reconciliation_sql_vs_python")
    tables = con.execute("SELECT table_name, estimated_size FROM duckdb_tables() ORDER BY table_name").df()
    con.close()
    if not rec["match"].all():
        raise RuntimeError(f"SQL and Python disagree:\n{rec[~rec['match']]}")
    summary = {"checks_passed": int((checks["failed_rows"] == 0).sum()), "checks_total": int(len(checks)),
               "queries": list(results), "reconciled_figures": int(len(rec)),
               "reconciled_matching": int(rec["match"].sum()),
               "tables": dict(zip(tables["table_name"], tables["estimated_size"].astype(int)))}
    io.save_json(summary, "p6", "p6_summary")
    print(f"P6  {summary['checks_passed']}/{summary['checks_total']} checks pass; {len(results)} queries; "
          f"{summary['reconciled_matching']}/{summary['reconciled_figures']} SQL figures match Python")
    return summary


if __name__ == "__main__":
    run()
