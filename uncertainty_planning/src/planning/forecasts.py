"""Point forecasts made with information available at a forecast origin.

Convention used everywhere: an *origin* ``t`` is the first month being forecast.
Only ``X[:, :t]`` (months before ``t``) may be used. A forecast for a *window* of
``w`` months is the expected demand summed over months ``t .. t + w - 1``; the
inventory policy needs this sum over its protection period (lead time + review).
"""
from __future__ import annotations

from typing import Callable

import numpy as np

Forecaster = Callable[[int, int], np.ndarray]


def point_forecast(X: np.ndarray, origin: int, window: int, method: str) -> np.ndarray:
    """Forecast of demand summed over ``window`` months starting at ``origin``."""
    if origin < 1:
        raise ValueError("origin must leave at least one month of history")
    hist = X[:, :origin]
    if method == "historical_average":
        return window * hist.mean(axis=1)
    if method == "naive":
        return window * hist[:, -1]
    if method == "moving_average_3":
        return window * hist[:, -3:].mean(axis=1)
    if method == "seasonal_naive":
        if origin < 12 or window > 12:
            raise ValueError("seasonal naive needs 12 months of history and window <= 12")
        return X[:, [origin + k - 12 for k in range(window)]].sum(axis=1)
    raise ValueError(f"unknown method {method!r}")


def make_forecaster(X: np.ndarray, method: str) -> Forecaster:
    return lambda origin, window: point_forecast(X, origin, window, method)


def window_actual(X: np.ndarray, origin: int, window: int) -> np.ndarray | None:
    """Actual demand summed over the window, or None if it runs past the data."""
    if origin + window > X.shape[1]:
        return None
    return X[:, origin:origin + window].sum(axis=1)


def wape(actual: np.ndarray, forecast: np.ndarray) -> float:
    actual, forecast = np.asarray(actual, float), np.asarray(forecast, float)
    return float(np.abs(actual - forecast).sum() / actual.sum())


def bias(actual: np.ndarray, forecast: np.ndarray) -> float:
    """Signed error as a share of actual demand (positive = over-forecast)."""
    actual, forecast = np.asarray(actual, float), np.asarray(forecast, float)
    return float((forecast - actual).sum() / actual.sum())


def rolling_point_errors(X: np.ndarray, forecaster: Forecaster, origins, window: int = 1):
    """Stack actuals and forecasts for every origin (series x origins)."""
    F = np.column_stack([forecaster(o, window) for o in origins])
    A = np.column_stack([window_actual(X, o, window) for o in origins])
    return A, F
