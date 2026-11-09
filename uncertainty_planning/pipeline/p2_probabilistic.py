"""P2 - Probabilistic forecasts: are the intervals honest?

1. Pick the point-forecast champion and the interval method on the selection
   period (Jul-Dec 2024) only, before looking at the test year.
2. Evaluate every combination on 2025: coverage of each quantile, interval
   width, scaled pinball loss and per-SKU calibration.
"""
import _bootstrap  # noqa: F401

import numpy as np
import pandas as pd
from scipy.stats import binom

from planning import config, io, plots
from planning.data import build_panel
from planning.forecasts import make_forecaster, rolling_point_errors, wape
from planning.uncertainty import QuantileModel, binomial_sd, interval_metrics, quantile_table


def selection_choices(panel, cal: int) -> dict:
    X = panel.X
    s0, s1 = panel.idx(config.SELECTION_PERIOD[0]), panel.idx(config.SELECTION_PERIOD[1])
    sel = list(range(s0, s1 + 1))
    point = {}
    for fm in config.FORECAST_METHODS:
        A, F = rolling_point_errors(X, make_forecaster(X, fm), sel)
        point[fm] = wape(A, F)
    champion_fm = min(point, key=point.get)

    pinball = {}
    for qm in config.QUANTILE_METHODS:
        losses = []
        for w in config.WINDOWS:
            origins = [o for o in sel if o + w - 1 <= s1]            # windows fully inside the period
            model = QuantileModel(X, make_forecaster(X, champion_fm), w, qm, cal)
            table = quantile_table(model, origins, config.EVAL_TAUS, panel.skus)
            losses.append(interval_metrics(table)["scaled_pinball"])
        pinball[qm] = float(np.mean(losses))
    champion_qm = min(pinball, key=pinball.get)
    return {"selection_period": config.SELECTION_PERIOD, "point_wape_h1": point,
            "forecast_method": champion_fm, "scaled_pinball": pinball, "quantile_method": champion_qm}


def run() -> dict:
    panel = build_panel()
    X, cal = panel.X, panel.idx(config.CALIBRATION_START)
    test = panel.year_idx(config.TEST_YEAR)
    choice = selection_choices(panel, cal)
    io.save_json(choice, "p2", "champion")

    # ------------------------------------------------ point accuracy on 2025
    point_rows = []
    for fm in config.FORECAST_METHODS:
        A, F = rolling_point_errors(X, make_forecaster(X, fm), test)
        point_rows.append({"method": fm, "sku_wape_h1": wape(A, F), "total_wape_h1": wape(A.sum(0), F.sum(0))})
    point_df = pd.DataFrame(point_rows)
    io.save_table(point_df, "p2", "point_accuracy_2025")

    # ---------------------------------------------- interval evaluation 2025
    metric_rows, tables = [], []
    for fm in config.FORECAST_METHODS:
        forecaster = make_forecaster(X, fm)
        for qm in config.QUANTILE_METHODS:
            for w in config.WINDOWS:
                model = QuantileModel(X, forecaster, w, qm, cal)
                origins = [o for o in test if o + w <= panel.n_months]
                table = quantile_table(model, origins, config.EVAL_TAUS, panel.skus)
                m = interval_metrics(table)
                metric_rows.append({"method": fm, "qmethod": qm, "window": w, **m})
                tables.append(table.assign(method=fm, qmethod=qm, window=w))
    metrics = pd.DataFrame(metric_rows)
    io.save_table(metrics, "p2", "interval_metrics_2025")
    qtable = pd.concat(tables, ignore_index=True)
    qtable["origin_month"] = [panel.months[o] for o in qtable["origin"]]
    io.save_processed(qtable.rename(columns={"series": "sku"}), "quantile_forecasts")

    # ------------------------------------------------------------- figures
    fm, qm = choice["forecast_method"], choice["quantile_method"]
    champ = qtable[(qtable["method"] == fm) & (qtable["window"] == 1)]
    curves = {}
    for q in config.QUANTILE_METHODS:
        g = champ[champ["qmethod"] == q]
        cov = g.groupby("tau").apply(lambda d: (d["actual"] <= d["quantile"]).mean())
        curves[config.QMETHOD_LABELS[q]] = (cov.index.to_numpy(), cov.to_numpy())
    plots.reliability(curves, io.figure_path("p2", "01_reliability"))
    plots.tail_reliability(curves, io.figure_path("p2", "02_tail_reliability"))

    # Per-SKU spread of 90% coverage is kept as a table metric (per_sku_coverage90_sd):
    # with 12 test months per SKU it is dominated by sampling noise (binomial sd ~0.087).

    # Fan charts: the top-revenue SKU and the most volatile SKU
    attrs = panel.attrs
    top = attrs["revenue"].idxmax()
    cv = pd.Series(X.std(1) / X.mean(1), index=panel.skus)
    volatile = cv.idxmax() if cv.idxmax() != top else cv.drop(top).idxmax()
    fan_model = QuantileModel(X, make_forecaster(X, fm), 1, qm, cal)
    for k, sku in enumerate([top, volatile], start=3):
        i = panel.skus.index(sku)
        qs = {tau: np.array([fan_model.quantile(t, tau)[i] for t in test]) for tau in config.FAN_TAUS}
        months = [panel.months[t] for t in test]
        hist = ([panel.months[t] for t in range(test[0])], X[i, :test[0]])
        plots.fan_chart(months, hist, X[i, test], qs,
                        f"{attrs.loc[sku, 'product_name']} ({sku}): forecast range vs actual",
                        io.figure_path("p2", f"0{k}_fan_{sku}"))

    # Calibration monitor: cumulative coverage of the 95% quantile through 2025
    monitor_rows, curves_m = [], {}
    g95 = champ[champ["tau"] == 0.95].assign(hit=lambda d: d["actual"] <= d["quantile"])
    for q in config.QUANTILE_METHODS:
        m = g95[g95["qmethod"] == q].groupby("origin_month")["hit"].agg(["sum", "count"]).cumsum()
        m["coverage"] = m["sum"] / m["count"]
        m["alarm_limit"] = binom.ppf(0.05, m["count"], 0.95) / m["count"]
        m["alarm"] = m["sum"] < binom.ppf(0.05, m["count"], 0.95)
        monitor_rows.append(m.reset_index().assign(qmethod=q))
        curves_m[config.QMETHOD_LABELS[q]] = m["coverage"].to_numpy()
    monitor = pd.concat(monitor_rows, ignore_index=True)
    io.save_table(monitor, "p2", "calibration_monitor_2025")
    plots.calibration_monitor(list(m.index), curves_m, m["alarm_limit"].to_numpy(), 0.95,
                              io.figure_path("p2", "05_calibration_monitor"))
    first_alarm = monitor[monitor["alarm"]].groupby("qmethod")["origin_month"].min().to_dict()

    champion_row = metrics[(metrics["method"] == fm) & (metrics["qmethod"] == qm) & (metrics["window"] == 1)].iloc[0]
    normal_row = metrics[(metrics["method"] == fm) & (metrics["qmethod"] == "normal") & (metrics["window"] == 1)].iloc[0]
    summary = {
        "champion": choice,
        "sku_wape_h1": float(point_df.set_index("method").loc[fm, "sku_wape_h1"]),
        "total_wape_h1": float(point_df.set_index("method").loc[fm, "total_wape_h1"]),
        "champion_interval": champion_row.to_dict(),
        "normal_interval": normal_row.to_dict(),
        "fan_chart_skus": [top, volatile],
        "expected_per_sku_sd_from_noise": binomial_sd(0.9, len(test)),
        "monitor_first_alarm": first_alarm,
    }
    io.save_json(summary, "p2", "p2_summary")
    print(f"P2  champion {fm} + {qm}; 2025 coverage@95 = {champion_row['coverage_0.95']:.3f} "
          f"(normal {normal_row['coverage_0.95']:.3f}); SKU WAPE {summary['sku_wape_h1']:.3f}")
    return summary


if __name__ == "__main__":
    run()
