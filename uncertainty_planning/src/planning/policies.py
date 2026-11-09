"""Build order-up-to levels from forecasts and run families of inventory policies."""
from __future__ import annotations

import numpy as np

from .forecasts import Forecaster
from .uncertainty import QuantileModel


def quantile_order_up_to(model: QuantileModel, tau, months: list[int], n_total: int) -> np.ndarray:
    """S_t = tau-quantile of protection-period demand (model.window = lead time + 1)."""
    n = model.X.shape[0]
    S = np.full((n, n_total), np.nan)
    for t in months:
        S[:, t] = model.quantile(t, tau)
    return S


def cover_order_up_to(forecaster: Forecaster, lead_time: int, cover_months: float,
                      months: list[int], n_series: int, n_total: int) -> np.ndarray:
    """Rule of thumb: expected protection-period demand + k months of forecast as buffer."""
    S = np.full((n_series, n_total), np.nan)
    for t in months:
        S[:, t] = forecaster(t, lead_time + 1) + cover_months * forecaster(t, 1)
    return S


def shifted_point_order_up_to(stat_model: QuantileModel, adjusted: Forecaster, tau,
                              months: list[int], n_total: int) -> np.ndarray:
    """A planner overrides the point forecast but keeps the system's safety stock."""
    n = stat_model.X.shape[0]
    S = np.full((n, n_total), np.nan)
    for t in months:
        safety = stat_model.quantile(t, tau) - stat_model.point(t)
        S[:, t] = np.maximum(adjusted(t, stat_model.window) + safety, 0.0)
    return S


def policy_id(lead_time: int, method: str, qmethod: str, target: str) -> str:
    return f"L{lead_time}|{method}|{qmethod}|{target}"


def target_label(target) -> str:
    """'sl95' for a uniform service level, otherwise the given label (e.g. 'cr_profit_h25')."""
    if isinstance(target, str):
        return target
    return f"sl{round(target * 100):02d}" if target * 100 % 1 == 0 else f"sl{target * 100:g}"


def cr_label(basis: str, holding_rate: float) -> str:
    return f"cr_{basis}_h{round(holding_rate * 100)}"
