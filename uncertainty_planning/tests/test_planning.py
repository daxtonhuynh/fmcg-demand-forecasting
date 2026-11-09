"""Unit tests for the planning building blocks (no dataset needed).

    python -m pytest uncertainty_planning/tests -q
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from planning.forecasts import make_forecaster, point_forecast  # noqa: E402
from planning.hierarchy import coherence_gap, reconcile, summing_matrix  # noqa: E402
from planning.inventory import critical_ratio, simulate  # noqa: E402
from planning.uncertainty import QuantileModel, conformal_quantile  # noqa: E402


def test_conformal_rank_is_finite_sample_conservative():
    errors = np.arange(1, 20, dtype=float)          # n = 19
    assert conformal_quantile(errors, 0.9)[0] == 18  # ceil(20 * 0.9) = 18th value
    assert conformal_quantile(errors, 0.1)[0] == 2   # floor(20 * 0.1) = 2nd value
    assert conformal_quantile(errors, 0.999)[0] == 19


def test_point_forecasts_use_only_the_past():
    rng = np.random.default_rng(0)
    X = rng.gamma(5, 100, size=(4, 30))
    Y = X.copy()
    Y[:, 20:] *= 10                                   # change the future only
    for method in ["historical_average", "naive", "moving_average_3", "seasonal_naive"]:
        assert np.allclose(point_forecast(X, 20, 2, method), point_forecast(Y, 20, 2, method))


def test_empirical_quantiles_cover_iid_demand():
    rng = np.random.default_rng(1)
    X = rng.gamma(9, 100, size=(40, 72))              # stationary demand, CV = 1/3
    model = QuantileModel(X, make_forecaster(X, "historical_average"), 1, "empirical", calibration_start=12)
    hits = [X[:, t] <= model.quantile(t, 0.9) for t in range(36, 72)]
    assert abs(np.mean(hits) - 0.9) < 0.03


def test_quantiles_increase_with_tau():
    rng = np.random.default_rng(2)
    X = rng.gamma(9, 100, size=(10, 40))
    for qm in ["normal", "empirical", "empirical_scaled"]:
        model = QuantileModel(X, make_forecaster(X, "historical_average"), 2, qm, calibration_start=12)
        qs = np.vstack([model.quantile(30, tau) for tau in [0.1, 0.5, 0.9, 0.99]])
        assert np.all(np.diff(qs, axis=0) >= -1e-9)


@pytest.mark.parametrize("lead_time", [0, 1, 2])
def test_simulation_conserves_stock(lead_time):
    rng = np.random.default_rng(3)
    D = rng.poisson(100, size=(5, 24)).astype(float)
    S = np.full((5, 25), 260.0) + rng.normal(0, 20, size=(5, 25))
    res = simulate(D, S, lead_time, start=4, end=24)
    assert np.allclose(res.closing, res.opening + res.receipts - res.sales)
    assert np.allclose(res.opening[:, 1:], res.closing[:, :-1])
    assert np.all(res.sales <= res.demand + 1e-9) and np.all(res.closing >= -1e-9)
    assert np.allclose(res.lost, res.demand - res.sales)


def test_orders_arrive_after_the_lead_time():
    D = np.array([[0, 0, 50, 0, 0, 0]], dtype=float)
    S = np.array([[10, 10, 10, 100, 100, 100, 100]], dtype=float)
    res = simulate(D, S, lead_time=2, start=0, end=6)
    # month 2 demand of 50 against 10 on hand loses 40; the month-3 order arrives in month 5
    assert res.lost[0, 2] == 40
    assert res.order_qty[0, 3] == 100 and res.receipts[0, 4] == 0 and res.receipts[0, 5] == 100


def test_no_lost_sales_when_stock_always_covers_demand():
    D = np.full((3, 12), 50.0)
    S = np.full((3, 13), 60.0)
    res = simulate(D, S, lead_time=0, start=0, end=12)
    assert res.lost.sum() == 0


def _attrs():
    return pd.DataFrame({
        "brand": ["A", "A", "B", "C"], "category": ["X", "X", "X", "Y"],
        "unit_cost": [1.0, 2.0, 1.5, 3.0], "unit_profit": [0.5, 0.1, 0.9, 1.2],
        "unit_gross_margin": [0.9, 0.6, 1.4, 2.0],
    }, index=["s1", "s2", "s3", "s4"])


def test_reconciled_forecasts_add_up():
    attrs = _attrs()
    S, meta = summing_matrix(attrs, list(attrs.index))
    assert S.shape == (1 + 2 + 3 + 4, 4)
    rng = np.random.default_rng(4)
    y_hat = rng.gamma(5, 100, size=S.shape[0])
    residuals = rng.normal(0, 10, size=(12, S.shape[0]))
    history = rng.gamma(5, 100, size=(4, 24))
    assert coherence_gap(y_hat, S) > 1e-6                  # unreconciled base forecasts do not add up
    for method in ["bottom_up", "top_down", "ols", "wls_structural", "mint_shrink"]:
        y = reconcile(method, y_hat, S, history_bottom=history, residuals=residuals)
        assert coherence_gap(y, S) < 1e-6, method


def test_historical_average_is_already_coherent():
    attrs = _attrs()
    S, _ = summing_matrix(attrs, list(attrs.index))
    X = np.random.default_rng(5).gamma(5, 100, size=(4, 24))
    y_hat = point_forecast(S @ X, 20, 1, "historical_average")
    assert coherence_gap(y_hat, S) < 1e-9


def test_critical_ratio_falls_as_holding_gets_dearer():
    attrs = _attrs()
    low, high = critical_ratio(attrs, 0.15, "profit"), critical_ratio(attrs, 0.35, "profit")
    assert np.all(high <= low) and np.all((low >= 0.5) & (low <= 0.995))
