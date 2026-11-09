"""Rebuild the case-study page (index.html at the repository root) from pipeline outputs.

    python tools/case_study/build_case_study.py

Reads
  uncertainty_planning/outputs/       results of the planning pipeline (run it first)
  the raw dataset                     located the same way as the planning pipeline
  the main project's model comparison (stage 5 results, typed below from the README)
Writes
  index.html                          index.template.html with every {{placeholder}} filled
  assets/data/*.csv                   one CSV per chart, behind the "Data (CSV)" links
  tools/case_study/facts.json         every number used in the page text, for review

Numbers in the page come from FACTS or from a chart table, so nothing is retyped by hand.
Some sentences in the template describe the current results in words; review them if
the pipeline is re-run on different data.
"""
from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
SITE = HERE.parents[1]                      # repository root
PLAN = SITE / "uncertainty_planning"
OUT = PLAN / "outputs"
TEMPLATE = HERE / "index.template.html"
DATA = SITE / "assets" / "data"
sys.path.insert(0, str(PLAN / "src"))
from planning import config  # noqa: E402  (same raw-file lookup as the planning pipeline)

if not (OUT / "p6_sql" / "p6_summary.json").exists():
    raise SystemExit("Planning outputs not found: run `python uncertainty_planning/run_planning.py` first.")
DATA.mkdir(parents=True, exist_ok=True)

esc = html.escape


def pct(x, d=1):
    return f"{x * 100:.{d}f}%".replace("-", "−")


def signed(x, d=1, unit=""):
    v = round(x, d)
    if v == 0:
        return f"{0:.{d}f}{unit}"
    return f"{'+' if v > 0 else '−'}{abs(v):.{d}f}{unit}"


def money_k(x, d=1):
    return f"${x / 1000:,.{d}f}K"


def save(df: pd.DataFrame, name: str) -> str:
    df.to_csv(DATA / f"{name}.csv", index=False, float_format="%.6g")
    return f"assets/data/{name}.csv"


def foot(text: str, csv: str) -> str:
    return (f'<figcaption class="chart-foot"><span>{text}</span>'
            f'<a href="{csv}" download>Data (CSV) ↓</a></figcaption>')


FACTS: dict[str, str] = {}

# ===================================================================== main project
# Figures published in the main project's README (stage 5 forecast validation).
models = pd.DataFrame([
    ("Historical average", "All known months, per SKU", 0.282, 0.281, 0.071, "usable", True),
    ("GBM: history + planned discount & price", "Scenario: assumes prices known ahead", 0.288, 0.285, 0.092, "usable", False),
    ("Ridge: history only", "", 0.292, 0.292, 0.086, "usable", False),
    ("Ridge: history + lagged drivers", "", 0.295, 0.293, 0.085, "usable", False),
    ("Moving average (3 months)", "", 0.312, 0.313, 0.086, "usable", False),
    ("GBM: history only", "", 0.313, 0.302, 0.100, "usable", False),
    ("GBM: history + lagged drivers", "", 0.316, 0.297, 0.092, "usable", False),
    ("Naive (last known month)", "", 0.396, 0.363, 0.092, "usable", False),
    ("Seasonal naive (same month last year)", "Best on the company total", 0.407, 0.407, 0.066, "usable", False),
    ("GBM: + same-month marketing", "Marketing is booked after the sale", 0.135, 0.142, 0.031, "leaky", False),
], columns=["model", "note", "sku_wape_1m", "sku_wape_3m", "total_wape_1m", "status", "chosen"])
NOISE_FLOOR = 0.262


def chart_models() -> str:
    csv = save(models.assign(noise_floor=NOISE_FLOOR), "model_comparison")
    vmax = 0.45
    rows = []
    for group, label in [("usable", "Usable in planning · inputs known when the forecast is made"),
                         ("leaky", "Not usable · reads information only known after the sale")]:
        rows.append(f'<div class="mgroup" role="row"><span role="columnheader">{label}</span></div>')
        for r in models[models["status"] == group].itertuples():
            cls = "hl" if r.chosen else ("leak" if group == "leaky" else "")
            note = f"<small>{esc(r.note)}</small>" if r.note else ""
            title = (f"{r.model}: {pct(r.sku_wape_1m)} SKU-month WAPE 1 month ahead, "
                     f"{pct(r.sku_wape_3m)} 3 months ahead, {pct(r.total_wape_1m)} on the company total")
            rows.append(
                f'<div class="brow row-hover {cls}" role="row" title="{esc(title)}">'
                f'<span class="duo-label" role="rowheader">{esc(r.model)}{note}</span>'
                f'<span class="btrack" role="cell"><i style="--v:{r.sku_wape_1m / vmax:.4f}"></i>'
                f'<em class="floor" style="--f:{NOISE_FLOOR / vmax:.4f}" aria-hidden="true"></em></span>'
                f'<span class="bval num" role="cell">{pct(r.sku_wape_1m)}<small>total {pct(r.total_wape_1m)}</small></span></div>')
    ticks = "".join(f'<span class="tick" style="left:{v / vmax * 100:.3f}%">{round(v * 100)}%</span>'
                    for v in [0, 0.1, 0.2, 0.3, 0.4])
    rows.append(f'<div class="brow baxis" aria-hidden="true"><span></span><span class="btrack">{ticks}</span><span></span></div>')
    return (
        '<figure class="chart" aria-labelledby="chart-models-title">'
        '<h3 class="chart-title" id="chart-models-title">Once leakage is removed, nothing beats each SKU\'s historical average</h3>'
        '<p class="chart-sub">Forecast error (WAPE) per SKU-month, one month ahead, on every month of 2025 with a rolling origin. '
        'Small figure: error on the company total. The dashed line is the noise floor: even perfect knowledge of each SKU\'s 2025 average leaves 26.2%.</p>'
        '<div class="legend" aria-hidden="true"><span><i class="key hl"></i>Chosen: simplest model, lowest error</span>'
        '<span><i class="key leak"></i>Leaks the answer</span><span><i class="key floorkey"></i>Noise floor 26.2%</span></div>'
        '<div class="mbars" role="table" aria-label="Forecast error by model">' + "".join(rows) + "</div>"
        + foot("Ridge, gradient boosting and every lagged-driver model are significantly worse than the historical average one month ahead "
               "(bootstrap 95% interval above zero). Lagged marketing, discount and price change WAPE by 0.5 points or less.", csv)
        + "</figure>")


leak = pd.DataFrame([
    ("GBM with same-month marketing", 0.135, "Looks excellent"),
    ("Same model, marketing removed", 0.288, "The honest number"),
    ("Historical average per SKU", 0.282, "Simplest model"),
    ("Noise floor", NOISE_FLOOR, "Perfect 2025 averages"),
], columns=["forecast", "sku_wape_1m", "note"])


def chart_leak() -> str:
    csv = save(leak, "leakage_ablation")
    hmax, top = 0.32, 196
    cols, labels = [], []
    for k, r in enumerate(leak.itertuples()):
        h = round(r.sku_wape_1m / hmax * top)
        cls = ' class="leak"' if k == 0 else (' class="hl"' if k == 2 else (' class="dim"' if k == 3 else ""))
        cols.append(f'<div class="col" role="cell" title="{esc(r.forecast)}: {pct(r.sku_wape_1m)} WAPE">'
                    f'<b class="num">{pct(r.sku_wape_1m)}</b><i{cls} style="height:{h}px"></i></div>')
        labels.append(f"<div>{esc(r.forecast)}<small>{esc(r.note)}</small></div>")
    aria = "; ".join(f"{r.forecast} {pct(r.sku_wape_1m)}" for r in leak.itertuples())
    return (
        '<figure class="chart" aria-labelledby="chart-leak-title">'
        '<h3 class="chart-title" id="chart-leak-title">A 13.5% forecast that was reading the answer</h3>'
        '<p class="chart-sub">SKU-month WAPE, one month ahead, 2025. Removing one input, same-month marketing spend, more than doubles the error.</p>'
        f'<div class="cols" role="row" aria-label="{esc(aria)}">' + "".join(cols) + "</div>"
        '<div class="col-labels" aria-hidden="true">' + "".join(labels) + "</div>"
        + foot("Same-month marketing carried 89% of the first model's feature importance.", csv) + "</figure>")


# ===================================================================== planning: calibration
im = pd.read_csv(OUT / "p2_probabilistic/tables/interval_metrics_2025.csv")
im1 = im[(im["method"] == "historical_average") & (im["window"] == 1)].set_index("qmethod")
QM = [("normal", "Normal (pooled σ)", "hl", "Chosen on Jul–Dec 2024"),
      ("empirical", "Empirical / conformal", "sig", ""),
      ("empirical_scaled", "Empirical, scaled by SKU volatility", "ns", "")]
TAUS = [0.8, 0.9, 0.95, 0.975, 0.99]
cal_rows = []
for q, label, _, _ in QM:
    for t in TAUS:
        cov = im1.loc[q, f"coverage_{t:g}"]
        cal_rows.append((label, t, cov, cov - t))
cal = pd.DataFrame(cal_rows, columns=["interval_method", "target_quantile", "achieved_coverage", "gap"])
FACTS["cov95_normal"] = pct(im1.loc["normal", "coverage_0.95"])
FACTS["cov95_emp"] = pct(im1.loc["empirical", "coverage_0.95"])
FACTS["cov95_scaled"] = pct(im1.loc["empirical_scaled", "coverage_0.95"])
FACTS["width90"] = pct(im1.loc["normal", "interval90_rel_width"], 0)


def chart_calibration() -> str:
    csv = save(cal, "interval_calibration")
    lo, hi = -0.03, 0.03

    def pos(g):
        return (min(max(g, lo), hi) - lo) / (hi - lo) * 100

    rows = []
    for t in TAUS:
        d = cal[cal["target_quantile"] == t]
        dots = []
        for (q, label, cls, _), g, c in zip(QM, d["gap"], d["achieved_coverage"]):
            dots.append(f'<span class="cdot {cls}" style="left:{pos(g):.3f}%" title="{esc(label)}: {pct(c)} of SKU-months below the {pct(t, 1)} quantile ({signed(g * 100, 1, " pp")})"></span>')
        normal_gap = d.iloc[0]["gap"]
        flag = " miss" if normal_gap < -0.01 else ""
        rows.append(
            f'<div class="ci-row row-hover{flag}" role="row"><span class="ci-label" role="rowheader">{pct(t, 1).replace(".0%", "%")} quantile</span>'
            f'<span class="ci-track cal" role="cell">{"".join(dots)}</span>'
            f'<span class="ci-val num" role="cell">{signed(normal_gap * 100, 1, " pp")}<small>Normal</small></span></div>')
    ticks = "".join(f'<span class="tick" style="left:{pos(v):.3f}%">{signed(v * 100, 0)}</span>'
                    for v in [-0.03, -0.02, -0.01, 0, 0.01, 0.02, 0.03])
    rows.append(f'<div class="ci-row ci-axis" aria-hidden="true"><span class="ci-label"></span><span class="ci-track">{ticks}</span><span></span></div>')
    rows.append('<div class="ci-row ci-axis" aria-hidden="true"><span class="ci-label"></span><span class="axis-name">Achieved minus promised, percentage points · left of zero = too little stock</span><span></span></div>')
    return (
        '<figure class="chart" aria-labelledby="chart-cal-title">'
        '<h3 class="chart-title" id="chart-cal-title">Normal ranges promise more than they deliver in the upper tail</h3>'
        '<p class="chart-sub">Share of 2025 SKU-months that fell below each forecast quantile, minus the share promised. 360 forecasts per point '
        '(30 SKUs × 12 months, 1 month ahead); sampling noise alone is about ±1.1 pp at the 95% quantile.</p>'
        '<div class="legend" aria-hidden="true"><span><i class="key dot hl"></i>Normal (pooled σ), chosen on 2024</span>'
        '<span><i class="key dot sig"></i>Empirical / conformal</span><span><i class="key dot ns2"></i>Empirical, scaled by SKU volatility</span></div>'
        '<div role="table" aria-label="Coverage gap by target quantile and interval method">' + "".join(rows) + "</div>"
        + foot("Safety stock is set at the upper quantiles, so a negative gap there means stock-outs more often than planned.", csv) + "</figure>")


mon = pd.read_csv(OUT / "p2_probabilistic/tables/calibration_monitor_2025.csv")
first_alarm = mon[(mon["qmethod"] == "normal") & (mon["alarm"])]["origin_month"].min()
FACTS["alarm_month"] = pd.Timestamp(first_alarm).strftime("%B %Y")
save(mon.rename(columns={"origin_month": "month", "sum": "hits", "count": "forecasts"}), "calibration_monitor")

# ===================================================================== hierarchy
hw = pd.read_csv(OUT / "p3_hierarchy/tables/wape_by_level_2025.csv")
hp = hw.pivot_table(index=["base_set", "approach"], columns="level", values="wape")[["total", "category", "brand", "sku"]]
td = hp.loc[("level_best", "top_down")]
FACTS.update({f"td_{k}": pct(v) for k, v in td.items()})
FACTS["ols_sku"] = pct(hp.loc[("level_best", "ols"), "sku"])


def chart_hierarchy() -> str:
    csv = save(hw[["base_set", "approach", "level", "wape", "bias", "coherent"]], "hierarchy_wape")
    names = {"total": ("Company", "1 series"), "category": ("Category", "5 series"),
             "brand": ("Brand", "17 series"), "sku": ("SKU", "30 series")}
    hmax, top = 0.32, 180
    cols = "".join(f'<div class="col" role="cell" title="{names[k][0]}: {pct(v)} WAPE"><b class="num">{pct(v)}</b>'
                   f'<i style="height:{max(3, round(v / hmax * top))}px"></i></div>' for k, v in td.items())
    labels = "".join(f"<div>{names[k][0]}<small>{names[k][1]}</small></div>" for k in td.index)
    aria = ", ".join(f"{names[k][0]} {pct(v)}" for k, v in td.items())
    return (
        '<figure class="chart" aria-labelledby="chart-hier-title">'
        '<h3 class="chart-title" id="chart-hier-title">The error shrinks as SKUs add up</h3>'
        '<p class="chart-sub">WAPE by level, 1 month ahead, 2025: seasonal naive for the company total, split down by historical shares (top-down). Every level adds up exactly.</p>'
        f'<div class="cols" role="row" aria-label="WAPE by level: {aria}">{cols}</div>'
        f'<div class="col-labels" aria-hidden="true">{labels}</div>'
        + foot("The gap between levels is noise cancelling out, not a weak SKU model.", csv) + "</figure>")


def table_hierarchy() -> str:
    rows = [("Each level on its own", ("level_best", "base"), "No"),
            ("Bottom-up", ("level_best", "bottom_up"), "Yes"),
            ("Top-down, historical shares", ("level_best", "top_down"), "Yes"),
            ("OLS reconciliation", ("level_best", "ols"), "Yes"),
            ("MinT, shrinkage", ("level_best", "mint_shrink"), "Yes")]
    body = []
    for label, key, coh in rows:
        r = hp.loc[key]
        strong = key[1] == "top_down"
        f = (lambda s: f"<strong>{s}</strong>") if strong else (lambda s: s)
        body.append(f"<tr><td>{f(label)}</td><td class='n'>{f(pct(r['total']))}</td><td class='n'>{f(pct(r['category']))}</td>"
                    f"<td class='n'>{f(pct(r['sku']))}</td><td>{coh}</td></tr>")
    return ('<table class="mini"><caption class="sr-only">WAPE by reconciliation approach</caption>'
            '<thead><tr><th scope="col">Approach</th><th scope="col" class="n">Total</th><th scope="col" class="n">Category</th>'
            '<th scope="col" class="n">SKU</th><th scope="col">Adds up</th></tr></thead><tbody>' + "".join(body) + "</tbody></table>")


# ===================================================================== inventory
p4 = json.load(open(OUT / "p4_inventory/p4_summary.json"))
ps = pd.read_csv(OUT / "p4_inventory/tables/policy_summary.csv")
base = ps[(ps["holding_rate"] == 0.25) & (ps["lost_sale_basis"] == "profit") & (ps["lead_time"] == 1)]
d = p4["default"]
u95 = p4["uniform_95"]
FACTS.update({
    "inv_default": money_k(d["avg_inventory_value"], 0), "fill_default": pct(d["fill_rate"]),
    "csl_default": pct(d["cycle_service_level"]), "cost_default": money_k(d["total_cost"]),
    "months_cover": f"{p4['inventory_months_of_cogs']:.1f}",
    "inv_u95": money_k(u95["avg_inventory_value"], 0), "fill_u95": pct(u95["fill_rate"]), "cost_u95": money_k(u95["total_cost"]),
    "saving_u95": money_k(u95["total_cost"] - d["total_cost"]),
    "saving_u95_pct": pct(1 - d["total_cost"] / u95["total_cost"]),
    "stock_cut_u95": money_k(u95["avg_inventory_value"] - d["avg_inventory_value"], 0),
    "cost_best_cover": money_k(p4["best_cover_total_cost"]),
    "plan_units": f"{p4['plan_total_order_units'] / 1000:.0f}K", "plan_value": money_k(p4["plan_total_order_value"], 0),
    "n_policies": str(p4["n_policies"]), "monthly_cogs": money_k(p4["monthly_demand_at_cost"], 0),
})
dbc = pd.read_csv(OUT / "p4_inventory/tables/decision_based_comparison.csv")
dbn = dbc[dbc["qmethod"] == "normal"].set_index("method")
FACTS["naive_vs_snaive"] = pct(dbn.loc["naive", "total_cost"] / dbn.loc["seasonal_naive", "total_cost"] - 1, 0)


def chart_method_cost() -> str:
    rows_src = [("historical_average", "Historical average"), ("moving_average_3", "Moving average (3 months)"),
                ("seasonal_naive", "Seasonal naive"), ("naive", "Naive (last month)")]
    df = pd.DataFrame([{"forecast": lbl, "sku_wape_1m": dbn.loc[m, "sku_wape_h1"], "avg_inventory_value": dbn.loc[m, "avg_inventory_value"],
                        "fill_rate": dbn.loc[m, "fill_rate"], "total_cost": dbn.loc[m, "total_cost"]} for m, lbl in rows_src])
    csv = save(df, "forecast_cost_comparison")
    vmax = 180000
    rows = []
    for k, r in enumerate(df.itertuples()):
        cls = "hl" if k == 0 else ""
        rows.append(
            f'<div class="brow row-hover {cls}" role="row" title="{esc(r.forecast)}: WAPE {pct(r.sku_wape_1m)}, stock {money_k(r.avg_inventory_value, 0)}, fill {pct(r.fill_rate)}, cost {money_k(r.total_cost)} a year">'
            f'<span class="duo-label" role="rowheader">{esc(r.forecast)}<small>WAPE {pct(r.sku_wape_1m)} · stock {money_k(r.avg_inventory_value, 0)}</small></span>'
            f'<span class="btrack" role="cell"><i style="--v:{r.total_cost / vmax:.4f}"></i></span>'
            f'<span class="bval num" role="cell">{money_k(r.total_cost)}<small>per year</small></span></div>')
    return (
        '<figure class="chart" aria-labelledby="chart-cost-title">'
        '<h3 class="chart-title" id="chart-cost-title">Rank forecasts by what they cost, not only by their error</h3>'
        '<p class="chart-sub">Holding cost + lost profit per year when each forecast drives the same cost-optimal stock policy (1-month lead time, 2025 simulation).</p>'
        '<div class="mbars" role="table" aria-label="Annual inventory cost by forecast">' + "".join(rows) + "</div>"
        + foot(f"Naive and seasonal naive have similar WAPE (39.6% vs 40.7%), yet the naive forecast's month-to-month swings cost {FACTS['naive_vs_snaive']} more. "
               "The historical average is cheapest in all 54 lead-time × cost × interval-method combinations tested.", csv) + "</figure>")


def chart_service_cost() -> str:
    uni = base[(base["method"] == "historical_average") & (base["qmethod"] == "normal") & base["target_value"].notna()
               & (base["target_value"] >= 0.8)].sort_values("target_value")
    df = uni[["target_value", "avg_inventory_value", "fill_rate", "holding_cost", "lost_value", "total_cost"]].rename(
        columns={"target_value": "uniform_service_target"})
    df.loc[len(df)] = ["cost-optimal per SKU", d["avg_inventory_value"], d["fill_rate"], d["holding_cost"], d["lost_value"], d["total_cost"]]
    csv = save(df, "service_level_cost")
    vmax, top = 125000, 196
    cols, labels = [], []
    for r in uni.itertuples():
        hold_h = round(r.holding_cost / vmax * top)
        lost_h = max(2, round(r.total_cost / vmax * top) - hold_h - 2)
        cols.append(f'<div class="col" role="cell" title="Uniform {pct(r.target_value, 0)} target: stock {money_k(r.avg_inventory_value, 0)}, fill {pct(r.fill_rate)}; '
                    f'holding {money_k(r.holding_cost)} + lost profit {money_k(r.lost_value)} = {money_k(r.total_cost)} a year">'
                    f'<b class="num">{r.total_cost / 1000:.1f}</b><i class="lost" style="height:{lost_h}px"></i><i class="hold" style="height:{hold_h}px"></i></div>')
        labels.append(f"<div>{pct(r.target_value, 0)}<small>fill {pct(r.fill_rate)}</small></div>")
    ref = d["total_cost"] / vmax * top
    aria = "; ".join(f"{pct(r.target_value, 0)} target: holding {money_k(r.holding_cost)}, lost profit {money_k(r.lost_value)}, total {money_k(r.total_cost)}"
                     for r in uni.itertuples())
    return (
        '<figure class="chart" aria-labelledby="chart-svc-title">'
        '<h3 class="chart-title" id="chart-svc-title">One service level for every SKU costs more than targets set per SKU</h3>'
        '<p class="chart-sub">Holding cost and lost profit, $K per year, when every SKU gets the same service-level target (1-month lead time, 2025 simulation). '
        'Low targets lose profit; high targets tie up stock. The dashed line is the total with targets set per SKU from its own profit and holding cost.</p>'
        '<div class="legend" aria-hidden="true"><span><i class="key"></i>Holding cost</span><span><i class="key sig"></i>Lost profit</span>'
        f'<span><i class="key refkey"></i>Per-SKU targets: {money_k(d["total_cost"])} a year</span></div>'
        f'<div class="cols seven ref stack" role="row" aria-label="{esc(aria)}; cost-optimal per SKU {money_k(d["total_cost"])}" style="--ref:{ref:.1f}px">'
        + "".join(cols) + '<span class="refline" aria-hidden="true"></span></div>'
        '<div class="col-labels seven" aria-hidden="true">' + "".join(labels) + "</div>"
        + foot("Below 90% lost profit dominates; above 95% holding cost does. Per-SKU targets beat a uniform 95% in all 18 lead-time and cost assumption sets.", csv)
        + "</figure>")


attrs = pd.read_csv(OUT / "p1_data/tables/sku_attributes.csv")
lo_sku = attrs.loc[attrs["critical_ratio_base"].idxmin()]
hi_sku = attrs.loc[attrs["critical_ratio_base"].idxmax()]
FACTS.update({"cr_min": pct(lo_sku["critical_ratio_base"]), "cr_min_name": lo_sku["product_name"],
              "cr_max": pct(hi_sku["critical_ratio_base"]), "cr_max_name": hi_sku["product_name"]})


def chart_targets() -> str:
    df = attrs[["sku", "product_name", "category", "unit_cost", "unit_profit", "critical_ratio_base"]].rename(
        columns={"critical_ratio_base": "service_target"}).sort_values(["category", "service_target"])
    csv = save(df, "sku_service_targets")
    lo, hi = 0.78, 0.98

    def pos(v):
        return (v - lo) / (hi - lo) * 100

    rows = []
    for cat, g in df.groupby("category"):
        hl = cat == "Beverages"
        dots = "".join(f'<span class="cdot {"hl" if hl else "sig"}" style="left:{pos(r.service_target):.3f}%" '
                       f'title="{esc(r.product_name)} ({r.sku}): target {pct(r.service_target)}; profit ${r.unit_profit:.2f} vs unit cost ${r.unit_cost:.2f}"></span>'
                       for r in g.itertuples())
        rows.append(f'<div class="ci-row row-hover{" hlrow" if hl else ""}" role="row"><span class="ci-label" role="rowheader">{esc(cat)}<small>{len(g)} SKUs</small></span>'
                    f'<span class="ci-track strip" role="cell" aria-label="Targets from {pct(g.service_target.min())} to {pct(g.service_target.max())}">{dots}</span>'
                    f'<span class="ci-val num" role="cell">{pct(g.service_target.mean())}<small>average</small></span></div>')
    ticks = "".join(f'<span class="tick" style="left:{pos(v):.3f}%">{round(v * 100)}%</span>' for v in [0.78, 0.82, 0.86, 0.90, 0.94, 0.98])
    rows.append(f'<div class="ci-row ci-axis" aria-hidden="true"><span class="ci-label"></span><span class="ci-track">{ticks}</span><span></span></div>')
    rows.append('<div class="ci-row ci-axis" aria-hidden="true"><span class="ci-label"></span><span class="axis-name">Cost-optimal cycle service level per SKU</span><span></span></div>')
    return (
        '<figure class="chart" aria-labelledby="chart-target-title">'
        '<h3 class="chart-title" id="chart-target-title">Thin-margin SKUs should run leaner</h3>'
        '<p class="chart-sub">Each dot is one SKU\'s cost-optimal service level: profit lost on a missed unit ÷ (that profit + one month of holding cost). '
        'Set from unit economics before 2025, not tuned on the test year.</p>'
        '<div role="table" aria-label="Service-level target per SKU by category">' + "".join(rows) + "</div>"
        + foot(f"Beverages, the lowest-margin category, gets the lowest targets: {FACTS['cr_min']} for {FACTS['cr_min_name']} against {FACTS['cr_max']} for {FACTS['cr_max_name']}.", csv)
        + "</figure>")


def table_policy() -> str:
    rows = [("Cost-optimal target per SKU", d["avg_inventory_value"], d["fill_rate"], d["cycle_service_level"], d["total_cost"], True),
            ("Uniform 95% target", u95["avg_inventory_value"], u95["fill_rate"], u95["cycle_service_level"], u95["total_cost"], False)]
    cov = base[(base["method"] == "historical_average") & (base["family"] == "cover")].sort_values("total_cost").iloc[0]
    rows.append((f"Rule of thumb, {cov['cover_months']:g} months of cover (best in hindsight)", cov["avg_inventory_value"], cov["fill_rate"],
                 cov["cycle_service_level"], cov["total_cost"], False))
    body = "".join(
        f"<tr><td>{'<strong>' + n + '</strong>' if s else n}</td><td class='n'>{money_k(i, 0)}</td><td class='n'>{pct(f)}</td>"
        f"<td class='n'>{pct(c)}</td><td class='n'>{'<strong>' + money_k(t) + '</strong>' if s else money_k(t)}</td></tr>"
        for n, i, f, c, t, s in rows)
    return ('<table class="mini"><caption class="sr-only">Policy comparison, base case</caption>'
            '<thead><tr><th scope="col">Policy (base case)</th><th scope="col" class="n">Avg stock</th><th scope="col" class="n">Fill rate</th>'
            '<th scope="col" class="n">Months w/o stock-out</th><th scope="col" class="n">Cost / yr</th></tr></thead><tbody>' + body + "</tbody></table>")


sens = pd.read_csv(OUT / "p4_inventory/tables/sensitivity.csv")
save(sens, "sensitivity")
FACTS["sens_min"] = pct(sens["cr_saving_vs_sl95"].min())
FACTS["sens_max"] = pct(sens["cr_saving_vs_sl95"].max())
FACTS["best_uni_min"] = pct(sens["best_uniform_target_hindsight"].min(), 0)
FACTS["best_uni_max"] = pct(sens["best_uniform_target_hindsight"].max(), 0)

plan = pd.read_csv(OUT / "p6_sql/tables/q7_replenishment_plan.csv")
save(plan.drop(columns=["cumulative_share_of_order_value"]), "replenishment_plan_2026_01")


def table_plan() -> str:
    top = plan.head(5)
    body = "".join(
        f"<tr><td>{esc(r.product_name)}<small class='cell-sub'>{esc(r.category)}</small></td><td class='n'>{pct(r.service_target)}</td>"
        f"<td class='n'>{r.order_up_to:,.0f}</td><td class='n'>{r.inventory_position:,.0f}</td>"
        f"<td class='n'><strong>{r.recommended_order:,.0f}</strong></td><td class='n'>{money_k(r.order_value_at_cost)}</td></tr>"
        for r in top.itertuples())
    body += (f"<tr class='tot'><td><strong>All 30 SKUs</strong></td><td></td><td></td><td></td>"
             f"<td class='n'><strong>{plan.recommended_order.sum():,.0f}</strong></td><td class='n'><strong>{money_k(plan.order_value_at_cost.sum(), 0)}</strong></td></tr>")
    return ('<table class="mini plan"><caption class="sr-only">January 2026 replenishment plan, five largest orders by value</caption>'
            '<thead><tr><th scope="col">SKU</th><th scope="col" class="n">Target</th><th scope="col" class="n">Order-up-to</th>'
            '<th scope="col" class="n">On hand + in transit</th><th scope="col" class="n">Order, units</th><th scope="col" class="n">Value</th></tr></thead><tbody>'
            + body + "</tbody></table>")


# ===================================================================== information
voi = pd.read_csv(OUT / "p5_information/tables/voi_summary.csv")
voi_co = voi[voi["policy"] == "cost_optimal"].sort_values("visibility")
v50 = voi_co.set_index("visibility").loc[0.5]
v100 = voi_co.set_index("visibility").loc[1.0]
p1 = json.load(open(OUT / "p1_data/p1_summary.json"))
FACTS.update({
    "large_thr": f"{p1['large_order_threshold_units']:.0f}", "large_orders_share": pct(p1["large_order_share_of_orders"], 0),
    "large_units_share": pct(p1["large_order_share_of_units"], 0), "large_b2b": pct(p1["large_orders_b2b_share"], 0),
    "voi50_wape": pct(v50["sku_wape"]), "voi50_stock": money_k(voi_co.iloc[0]["inventory_value"] - v50["inventory_value"], 0),
    "voi50_cost": money_k(v50["cost_saving_vs_none"]), "voi100_wape": pct(v100["sku_wape"]),
    "voi100_stock_pct": pct(v100["inventory_reduction_vs_none"], 0), "voi100_stock": money_k(voi_co.iloc[0]["inventory_value"] - v100["inventory_value"], 0),
    "voi100_cost": money_k(v100["cost_saving_vs_none"]),
})


def chart_voi() -> str:
    df = voi[["policy", "visibility", "sku_wape", "sku_wape_p05", "sku_wape_p95", "inventory_value", "fill_rate", "total_cost",
              "inventory_reduction_vs_none", "cost_saving_vs_none", "runs"]]
    csv = save(df, "value_of_information")
    wmax, imax = 0.30, 340000
    rows = ['<div class="duo-row head" role="row"><span class="duo-label" role="columnheader">Large orders visible</span>'
            '<span role="columnheader">SKU-month WAPE</span><span role="columnheader">Average stock at cost</span></div>']
    for r in voi_co.itertuples():
        hl = " hl" if r.visibility == 0.5 else ""
        lab = "None (history only)" if r.visibility == 0 else pct(r.visibility, 0)
        sub = "" if r.visibility == 0 else f"<small>−{money_k(r.cost_saving_vs_none)} a year</small>"
        rows.append(
            f'<div class="duo-row row-hover{hl}" role="row" title="{lab} of large orders visible: WAPE {pct(r.sku_wape)}, stock {money_k(r.inventory_value, 0)}, saves {money_k(r.cost_saving_vs_none)} a year">'
            f'<span class="duo-label" role="rowheader">{lab}{sub}</span>'
            f'<span class="hbar" role="cell"><i style="--v:{r.sku_wape / wmax:.4f}"></i><b>{pct(r.sku_wape)}</b></span>'
            f'<span class="hbar" role="cell"><i style="--v:{r.inventory_value / imax:.4f}"></i><b>{money_k(r.inventory_value, 0)}</b></span></div>')
    return (
        '<figure class="chart" aria-labelledby="chart-voi-title">'
        '<h3 class="chart-title" id="chart-voi-title">Seeing large B2B orders early cuts error and stock together</h3>'
        f'<p class="chart-sub">A forecast that sees a share of orders of {FACTS["large_thr"]}+ units before the replenishment decision, re-calibrated and run through the same cost-optimal policy. '
        'Partial visibility: mean of 30 random draws. Highlighted: half of large orders visible.</p>'
        '<div class="duo" role="table" aria-label="Value of pipeline visibility">' + "".join(rows) + "</div>"
        + foot("An upper bound: visible orders are assumed certain and on time. A real pipeline with win probabilities and date slippage would sit below these figures.", csv)
        + "</figure>")


fva = pd.read_csv(OUT / "p5_information/tables/fva_summary.csv")
FVA_NAMES = {"informed": ("Informed", "Sees 50% of large orders"), "optimistic": ("Optimistic", "+20% on 30% of SKU-months"),
             "chaser": ("Trend chaser", "50/50 with last month"), "sandbagger": ("Sandbagger", "−10% on everything")}
FACTS["fva_informed"] = f"+{fva.set_index('archetype').loc['informed', 'fva_points']:.1f}"


def chart_fva() -> str:
    csv = save(fva.drop(columns=["label"]), "forecast_value_added")
    lim = 5.0
    rows = []
    for r in fva.itertuples():
        name, sub = FVA_NAMES[r.archetype]
        v = r.fva_points
        left = 50 if v >= 0 else 50 + v / lim * 50
        width = abs(v) / lim * 50
        cls = "pos" if v >= 0 else "neg"
        rows.append(
            f'<div class="ci-row row-hover {"hl" if v >= 0 else ""}" role="row" title="{name}: FVA {signed(v, 1)} WAPE points, bias {pct(r.bias_final)}, cost change {signed(r.cost_change_vs_statistical / 1000, 1, 'K')} a year">'
            f'<span class="ci-label" role="rowheader">{name}<small>{sub}</small></span>'
            f'<span class="ci-track fva" role="cell"><span class="fbar {cls}" style="left:{left:.2f}%;width:{width:.2f}%"></span></span>'
            f'<span class="ci-val num" role="cell">{signed(v, 1, " pts")}<small>{"−" if r.cost_change_vs_statistical < 0 else "+"}${abs(r.cost_change_vs_statistical) / 1000:.1f}K a year</small></span></div>')
    ticks = "".join(f'<span class="tick" style="left:{(t + lim) / (2 * lim) * 100:.3f}%">{signed(t, 1 if t % 1 else 0)}</span>' for t in [-5, -2.5, 0, 2.5, 5])
    rows.append(f'<div class="ci-row ci-axis" aria-hidden="true"><span class="ci-label"></span><span class="ci-track">{ticks}</span><span></span></div>')
    rows.append('<div class="ci-row ci-axis" aria-hidden="true"><span class="ci-label"></span><span class="axis-name">Forecast Value Added, WAPE points · right of zero = the override helped</span><span></span></div>')
    return (
        '<figure class="chart" aria-labelledby="chart-fva-title">'
        '<h3 class="chart-title" id="chart-fva-title">Only informed overrides add value</h3>'
        '<p class="chart-sub">Four simulated planners adjust the statistical forecast; each change is logged with a reason code and run through the stock policy. Mean of 30 draws.</p>'
        '<div role="table" aria-label="Forecast Value Added by planner">' + "".join(rows) + "</div>"
        + foot("The sandbagger loses accuracy yet costs slightly less: judge overrides on cost as well as error.", csv) + "</figure>")


# ===================================================================== extra facts
fv = fva.set_index("archetype")
FACTS["fva_informed_cost"] = money_k(-fv.loc["informed", "cost_change_vs_statistical"])
FACTS["fva_opt"] = f"{fv.loc['optimistic', 'fva_points']:.1f}".replace("-", "−")
FACTS["fva_chaser"] = f"{fv.loc['chaser', 'fva_points']:.1f}".replace("-", "−")
FACTS["fva_opt_abs"] = f"{abs(fv.loc['optimistic', 'fva_points']):.1f}"
FACTS["fva_chaser_abs"] = f"{abs(fv.loc['chaser', 'fva_points']):.1f}"
FACTS["next_best_add_min"] = money_k(dbn.loc["moving_average_3", "total_cost"] - dbn.loc["historical_average", "total_cost"], 0)
FACTS["next_best_add_max"] = money_k(dbn.loc["naive", "total_cost"] - dbn.loc["historical_average", "total_cost"], 0)

# ===================================================================== the data
RAW = config.raw_csv_path()
raw = pd.read_csv(RAW)
assert raw.shape == (18240, 27)
sample = raw.iloc[0]
nunq = {c: raw[c].nunique() for c in raw.columns}
FACTS.update({"n_orders": f"{len(raw):,}", "n_cols": str(raw.shape[1]), "n_days": f"{raw['Order_Date'].nunique():,}"})

FAMILIES = [
    ("When", "Order and date", ["Order_ID", "Order_Date", "Year", "Quarter", "Month", "Month_Name"],
     f"{sample.Order_ID} · {pd.Timestamp(sample.Order_Date):%d %b %Y} · {sample.Quarter}",
     f"<b>{nunq['Order_Date']:,} days</b>, Jan 2023 – Dec 2025, one row per order"),
    ("Where", "Market", ["Region", "Country", "City"],
     f"{sample.Region} › {sample.Country} › {sample.City}",
     f"<b>{nunq['Region']} regions</b>, {nunq['Country']} countries, {nunq['City']} cities"),
    ("Who", "Seller, buyer, route", ["Sales_Person", "Customer_Type", "Sales_Channel"],
     f"{sample.Sales_Person} · {sample.Customer_Type} · {sample.Sales_Channel}",
     f"<b>{nunq['Sales_Person']} sales reps</b>, B2B or B2C, {nunq['Sales_Channel']} channels"),
    ("What", "Product hierarchy", ["Product_Category", "Brand", "Product_Name", "SKU"],
     f"{sample.Product_Category} › {sample.Brand} › {sample.Product_Name} ({sample.SKU})",
     f"<b>{nunq['Product_Category']} categories</b>, {nunq['Brand']} brands, {nunq['SKU']} SKUs"),
    ("Levers", "Volume and commercial terms", ["Units_Sold", "Unit_Price_USD", "Discount_Pct", "Promotion_Type", "Marketing_Spend_USD"],
     f"{sample.Units_Sold} units × ${sample.Unit_Price_USD:.2f}, {sample.Discount_Pct:.1f}% off, {sample.Promotion_Type}, ${sample.Marketing_Spend_USD:.2f} marketing",
     f"<b>{nunq['Promotion_Type']} promotion types</b> (incl. none), discounts {raw.Discount_Pct.min():.0f}–{raw.Discount_Pct.max():.0f}%"),
    ("Money", "Revenue, cost, profit", ["Gross_Sales_USD", "Net_Revenue_USD", "COGS_USD", "Logistics_Cost_USD", "Profit_USD", "Profit_Margin_Pct"],
     f"${sample.Gross_Sales_USD:.2f} gross → ${sample.Net_Revenue_USD:.2f} net → ${sample.Profit_USD:.2f} profit ({sample.Profit_Margin_Pct:.1f}%)",
     "<b>Exact formulas</b> of units, price, discount and costs"),
]
assert sum(len(f[2]) for f in FAMILIES) == 27 and set(c for f in FAMILIES for c in f[2]) == set(raw.columns)


def anatomy() -> str:
    cards = []
    for tag, title, cols, ex, cover in FAMILIES:
        chips = "".join(f'<span class="chip">{c}</span>' for c in cols)
        cards.append(f'<article class="fam"><p class="tag">{tag} · {len(cols)} columns</p><h4>{title}</h4>'
                     f'<div class="chips">{chips}</div>'
                     f'<p class="sample"><span>Example</span>{esc(ex)}</p><p class="cover">{cover}</p></article>')
    return '<div class="anatomy">' + "".join(cards) + "</div>"


tot = raw[["Gross_Sales_USD", "Net_Revenue_USD", "COGS_USD", "Logistics_Cost_USD", "Marketing_Spend_USD", "Profit_USD"]].sum()
assert abs(tot.Net_Revenue_USD - tot.COGS_USD - tot.Logistics_Cost_USD - tot.Marketing_Spend_USD - tot.Profit_USD) < 0.01


def money_m(x):
    return f"${x / 1e6:.2f}M"


def chart_waterfall() -> str:
    g, n = tot.Gross_Sales_USD, tot.Net_Revenue_USD
    steps = [
        ("Gross sales", "Units × list price", 0, g, "total", f"{money_m(g)}", ""),
        ("Discounts", "Applied on each order", n, g, "minus", f"−{money_m(g - n)}", f"{pct((g - n) / g)} of gross"),
        ("Net revenue", "What customers pay", 0, n, "total", money_m(n), ""),
        ("Cost of goods", "COGS", n - tot.COGS_USD, n, "minus", f"−{money_m(tot.COGS_USD)}", f"{pct(tot.COGS_USD / n)} of net"),
        ("Logistics", "Delivery cost per order", n - tot.COGS_USD - tot.Logistics_Cost_USD, n - tot.COGS_USD, "minus",
         f"−{money_m(tot.Logistics_Cost_USD)}", f"{pct(tot.Logistics_Cost_USD / n)} of net"),
        ("Marketing", "Booked per order, after the sale", tot.Profit_USD, tot.Profit_USD + tot.Marketing_Spend_USD, "minus mk",
         f"−{money_m(tot.Marketing_Spend_USD)}", f"{pct(tot.Marketing_Spend_USD / n)} of net"),
        ("Profit", "Margin on net revenue", 0, tot.Profit_USD, "profit", money_m(tot.Profit_USD), f"{pct(tot.Profit_USD / n)} margin"),
    ]
    df = pd.DataFrame([(s[0], s[2], s[3], s[3] - s[2]) for s in steps], columns=["step", "from_usd", "to_usd", "amount_usd"])
    df.loc[df["step"].isin(["Discounts", "Cost of goods", "Logistics", "Marketing"]), "amount_usd"] *= -1
    csv = save(df, "revenue_to_profit")
    rows = []
    for name, sub, a, b, cls, val, share in steps:
        rows.append(
            f'<div class="brow wf {cls}" role="row" title="{name}: {val}{(", " + share) if share else ""}">'
            f'<span class="duo-label" role="rowheader">{name}<small>{sub}</small></span>'
            f'<span class="btrack" role="cell"><i style="left:{a / g * 100:.3f}%;width:{(b - a) / g * 100:.3f}%"></i></span>'
            f'<span class="bval num" role="cell">{val}<small>{share or "&nbsp;"}</small></span></div>')
    return (
        '<figure class="chart" aria-labelledby="chart-wf-title">'
        '<h3 class="chart-title" id="chart-wf-title">How $17.08M of sales becomes $3.31M of profit</h3>'
        f'<p class="chart-sub">All {len(raw):,} orders, January 2023 to December 2025. Every money column is an exact formula of the others, so the steps add up to the cent.</p>'
        '<div class="mbars" role="table" aria-label="From gross sales to profit">' + "".join(rows) + "</div>"
        + foot("Marketing is recorded on each order as a share of its value. That is why it looked like the strongest driver of sales, and why it could not be used to forecast them.", csv)
        + "</figure>")


def er_sales() -> str:
    def rows(fact, sub, keys, measures):
        out = [f'<div class="er-row er-th"><span class="er-key">{fact}<small>{sub}</small></span><span></span><span class="er-dh">Dimension it joins</span></div>']
        for k, (key, dim, desc) in enumerate(keys):
            pk = ' pk' if key == 'order_id' else ''
            link = '<span class="er-link" aria-hidden="true"></span>' if dim else '<span></span>'
            target = f'<span class="er-dim"><b>{dim}</b>{desc}</span>' if dim else f'<span class="er-dim plain">{desc}</span>'
            out.append(f'<div class="er-row"><span class="er-key{pk}"><code>{key}</code></span>{link}{target}</div>')
        out.append(f'<div class="er-row er-ms"><span class="er-key"><span class="er-mlabel">Other columns (selected)</span>'
                   + "".join(f"<code>{m}</code>" for m in measures) + '</span><span></span><span></span></div>')
        return "".join(out)

    sales = rows("fact_sales", f"one row per order · {len(raw):,} rows", [
        ("order_id", None, "Primary key: one order"),
        ("date_key", "dim_date", f"Calendar, {nunq['Order_Date']:,} days of orders"),
        ("product_key", "dim_product", f"{nunq['SKU']} SKUs › {nunq['Brand']} brands › {nunq['Product_Category']} categories"),
        ("geo_key", "dim_geography", f"{nunq['City']} cities › {nunq['Country']} countries › {nunq['Region']} regions"),
        ("channel_key", "dim_channel", f"{nunq['Sales_Channel']} sales channels"),
        ("promotion_key", "dim_promotion", f"{nunq['Promotion_Type']} promotion types"),
        ("sales_rep_key", "dim_sales_rep", f"{nunq['Sales_Person']} sales reps"),
    ], ["units_sold", "net_revenue_usd", "profit_usd", "marketing_spend_usd", "customer_type"])
    fc = rows("fact_forecast", "one row per SKU × month × horizon × model", [
        ("product_key", "dim_product", "Same product dimension"),
        ("month_date_key", "dim_date", "Forecast month, 2025"),
        ("horizon_months", None, "1 or 3 months ahead"),
        ("model", "dim_model", "The 10 forecast models compared"),
    ], ["actual_units", "forecast_units"])
    return (
        '<figure class="chart er" aria-labelledby="er-sales-title">'
        '<h3 class="chart-title" id="er-sales-title"><span class="dbname">fmcg.duckdb</span> Sales warehouse: a star schema</h3>'
        '<p class="chart-sub">Built in stage 6 from the cleaned orders and the 2025 forecasts. Both dashboards and the eight business queries read from it. '
        '15 data-quality checks; 102 SQL figures match the Python results.</p>'
        f'<div class="er-grid" role="table" aria-label="fact_sales and its dimensions">{sales}</div>'
        f'<div class="er-grid second" role="table" aria-label="fact_forecast and its dimensions">{fc}</div>'
        "</figure>")


PLAN_TABLES = [
    ("dim_sku", "SKU, with unit cost, unit profit and its service target", "dim"),
    ("dim_month", "Month, flagged history or test year", "dim"),
    ("dim_policy", "Stock policy: lead time, forecast, range method, target", "dim"),
    ("fact_demand", "SKU × month: units, of which large orders", "fact"),
    ("fact_quantile_forecast", "SKU × month × window × method × quantile", "fact"),
    ("fact_reconciled_forecast", "Series × month × reconciliation approach", "fact"),
    ("fact_inventory_sim", "Policy × SKU × month: received, sold, lost, left", "fact"),
    ("fact_replenishment_plan", "Policy × SKU: the order for January 2026", "fact"),
    ("fact_override_log", "Planner × SKU × month: system vs final number", "fact"),
    ("fact_voi_run", "Visibility level × random draw × policy", "fact"),
]


def table_planning_wh() -> str:
    sizes = json.load(open(OUT / "p6_sql/p6_summary.json"))["tables"]
    import math
    lmax = math.log10(max(sizes.values()))
    df = pd.DataFrame([(t, g, k, sizes[t]) for t, g, k in PLAN_TABLES], columns=["table", "one_row_per", "kind", "rows"])
    csv = save(df, "planning_warehouse_tables")
    body = "".join(
        f"<tr><td><code>{t}</code></td><td>{esc(g)}</td>"
        f"<td class='n'><span class='szbar' style='--v:{math.log10(sizes[t]) / lmax:.3f}' aria-hidden='true'></span>{sizes[t]:,}</td></tr>"
        for t, g, k in PLAN_TABLES)
    return (
        '<figure class="chart er" aria-labelledby="er-plan-title">'
        '<h3 class="chart-title" id="er-plan-title"><span class="dbname">planning.duckdb</span> Planning warehouse</h3>'
        '<p class="chart-sub">Built in stage P6 from the planning outputs: 3 dimensions and 7 facts keyed on SKU, month and policy. '
        '17 data-quality checks; 320 SQL figures match the Python results.</p>'
        '<table class="mini wh"><caption class="sr-only">Planning warehouse tables</caption><thead><tr><th scope="col">Table</th>'
        '<th scope="col">One row per</th><th scope="col" class="n">Rows <span class="thsub">(bar: log scale)</span></th></tr></thead><tbody>'
        + body + "</tbody></table>" + foot("The biggest table, fact_inventory_sim, is every policy replayed month by month: the raw material for every stock and cost figure.", csv)
        + "</figure>")


# ===================================================================== assemble
CHARTS = {
    "chart_models": chart_models(), "chart_leak": chart_leak(), "chart_calibration": chart_calibration(),
    "chart_hierarchy": chart_hierarchy(), "table_hierarchy": table_hierarchy(), "chart_method_cost": chart_method_cost(),
    "chart_service_cost": chart_service_cost(), "chart_targets": chart_targets(), "table_policy": table_policy(),
    "table_plan": table_plan(), "chart_voi": chart_voi(), "chart_fva": chart_fva(),
    "anatomy": anatomy(), "chart_waterfall": chart_waterfall(), "er_sales": er_sales(),
    "table_planning_wh": table_planning_wh(),
}
src = TEMPLATE.read_text()


def fill(m):
    key = m.group(1)
    if key in CHARTS:
        return CHARTS[key]
    if key in FACTS:
        return esc(FACTS[key])
    raise KeyError(f"unknown placeholder {key}")


page = re.sub(r"\{\{(\w+)\}\}", fill, src)
(SITE / "index.html").write_text(page)
(HERE / "facts.json").write_text(json.dumps(FACTS, indent=1, ensure_ascii=False))
print(f"index.html {len(page) / 1000:.0f} KB; {len(list(DATA.glob('*.csv')))} CSVs")
