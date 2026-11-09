"""Turn point forecasts into quantile forecasts using only past forecast errors.

For a target origin ``t`` the calibration set is every earlier origin ``o`` whose
whole window was observed before ``t`` (``o + window - 1 <= t - 1``) and
``o >= calibration start``. Errors are relative to the forecast,
``e = (actual - forecast) / forecast``, pooled across SKUs.

Methods
- ``normal``: textbook buffer, ``q = F * (1 + z_tau * sd(e))``.
- ``empirical``: split-conformal quantile of the pooled errors, with the
  finite-sample rank ``ceil((n + 1) * tau)``.
- ``empirical_scaled``: same, but errors are first divided by each SKU's
  volatility (coefficient of variation of its monthly demand, known at the
  origin) and multiplied back, so volatile SKUs get wider intervals.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy.stats import norm

from . import config
from .forecasts import Forecaster, window_actual


def conformal_quantile(sorted_errors: np.ndarray, tau) -> np.ndarray:
    """Finite-sample conformal quantile (upper rank for tau >= .5, lower rank below)."""
    n = len(sorted_errors)
    tau = np.atleast_1d(np.asarray(tau, dtype=float))
    upper = np.ceil((n + 1) * tau).astype(int)
    lower = np.floor((n + 1) * tau).astype(int)
    k = np.where(tau >= 0.5, upper, lower)
    k = np.clip(k, 1, n)
    return sorted_errors[k - 1]


def volatility(X: np.ndarray, origin: int) -> np.ndarray:
    """Coefficient of variation of monthly demand up to (not including) ``origin``."""
    hist = X[:, :origin]
    mean = hist.mean(axis=1)
    sd = hist.std(axis=1, ddof=1)
    return np.where(mean > 0, sd / np.maximum(mean, 1e-9), 1.0)


class QuantileModel:
    """Quantile forecasts for one (point forecaster, window, method) combination."""

    def __init__(self, X: np.ndarray, forecaster: Forecaster, window: int, qmethod: str,
                 calibration_start: int, min_errors: int = config.MIN_CALIBRATION_ERRORS):
        if qmethod not in config.QUANTILE_METHODS:
            raise ValueError(f"unknown quantile method {qmethod!r}")
        self.X, self.forecaster, self.window, self.qmethod = X, forecaster, window, qmethod
        self.calibration_start, self.min_errors = calibration_start, min_errors
        self._points: dict[int, np.ndarray] = {}
        self._errors: dict[int, np.ndarray] = {}

    # ---------------------------------------------------------------- pieces
    def point(self, origin: int) -> np.ndarray:
        if origin not in self._points:
            self._points[origin] = np.maximum(self.forecaster(origin, self.window), 1e-9)
        return self._points[origin]

    def _relative_errors(self, origin: int) -> np.ndarray:
        actual = window_actual(self.X, origin, self.window)
        error = (actual - self.point(origin)) / self.point(origin)
        if self.qmethod == "empirical_scaled":
            error = error / volatility(self.X, origin)
        return error

    def calibration_errors(self, origin: int) -> np.ndarray:
        """Pooled errors known at ``origin`` (sorted)."""
        if origin not in self._errors:
            last = origin - self.window          # last origin whose window ended before `origin`
            past = [self._relative_errors(o) for o in range(self.calibration_start, last + 1)]
            self._errors[origin] = np.sort(np.concatenate(past)) if past else np.array([])
        return self._errors[origin]

    def available(self, origin: int) -> bool:
        return len(self.calibration_errors(origin)) >= self.min_errors

    # -------------------------------------------------------------- quantile
    def quantile(self, origin: int, tau) -> np.ndarray:
        """Quantile of window demand at ``origin``; ``tau`` is a scalar or one per series."""
        errors = self.calibration_errors(origin)
        if len(errors) < self.min_errors:
            raise ValueError(f"only {len(errors)} calibration errors at origin {origin}")
        point = self.point(origin)
        tau = np.broadcast_to(np.asarray(tau, dtype=float), point.shape)
        if self.qmethod == "normal":
            sd = errors.std(ddof=1)
            mult = 1 + norm.ppf(tau) * sd
        elif self.qmethod == "empirical":
            mult = 1 + conformal_quantile(errors, tau)
        else:  # empirical_scaled
            mult = 1 + volatility(self.X, origin) * conformal_quantile(errors, tau)
        return np.maximum(point * mult, 0.0)


# ------------------------------------------------------------------ evaluation
def quantile_table(model: QuantileModel, origins, taus, series_ids) -> pd.DataFrame:
    """Long table of quantiles, point forecast and actual for evaluation origins."""
    rows = []
    for origin in origins:
        if not model.available(origin):
            continue
        actual = window_actual(model.X, origin, model.window)
        point = model.point(origin)
        for tau in taus:
            q = model.quantile(origin, tau)
            for i, sid in enumerate(series_ids):
                rows.append((sid, origin, tau, q[i], point[i],
                             np.nan if actual is None else actual[i]))
    return pd.DataFrame(rows, columns=["series", "origin", "tau", "quantile", "forecast", "actual"])


def pinball(actual, q, tau):
    diff = actual - q
    return np.maximum(tau * diff, (tau - 1) * diff)


def interval_metrics(table: pd.DataFrame) -> dict:
    """Calibration and sharpness summary of one quantile table (rows with actuals)."""
    t = table.dropna(subset=["actual"])
    mean_actual = t.loc[t["tau"] == t["tau"].iloc[0], "actual"].mean()
    out = {}
    for tau, g in t.groupby("tau"):
        out[f"coverage_{tau:g}"] = float((g["actual"] <= g["quantile"]).mean())
    out["scaled_pinball"] = float(
        t.assign(loss=pinball(t["actual"], t["quantile"], t["tau"]))["loss"].mean() / mean_actual
    )
    wide = t.pivot_table(index=["series", "origin"], columns="tau", values="quantile")
    act = t.groupby(["series", "origin"])["actual"].first().reindex(wide.index)
    for lo, hi, name in [(0.10, 0.90, "80"), (0.05, 0.95, "90")]:
        if lo in wide and hi in wide:
            inside = (act >= wide[lo]) & (act <= wide[hi])
            out[f"interval{name}_coverage"] = float(inside.mean())
            out[f"interval{name}_rel_width"] = float(((wide[hi] - wide[lo]) / act.mean()).mean())
    if 0.9 in wide:
        per_series = (act <= wide[0.9]).groupby(level="series").mean()
        out["per_sku_coverage90_sd"] = float(per_series.std(ddof=0))
        out["per_sku_coverage90_min"] = float(per_series.min())
        out["per_sku_coverage90_max"] = float(per_series.max())
    out["n_forecasts"] = int(len(wide))
    return out


def binomial_sd(p: float, n: int) -> float:
    """Spread of per-SKU coverage expected from sampling noise alone."""
    return math.sqrt(p * (1 - p) / n)
