"""Coherent forecasts across Total -> Category -> Brand -> SKU.

Reconciliation maps base forecasts of all 53 series onto bottom-level (SKU)
forecasts ``b = G @ y_hat`` and sums them back up ``y_tilde = S @ b``, so every
level adds up by construction. Formulas follow Hyndman & Athanasopoulos,
*Forecasting: Principles and Practice*, ch. 11 and Wickramasuriya et al. (2019).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def summing_matrix(attrs: pd.DataFrame, skus: list) -> tuple[np.ndarray, pd.DataFrame]:
    """Rows: total, categories, brands, SKUs. Columns: SKUs (in ``skus`` order)."""
    a = attrs.loc[skus]
    rows, meta = [np.ones(len(skus))], [("total", "Total")]
    for level, col in [("category", "category"), ("brand", "brand")]:
        for name in sorted(a[col].unique()):
            rows.append((a[col] == name).to_numpy(float))
            meta.append((level, name))
    for i, sku in enumerate(skus):
        row = np.zeros(len(skus))
        row[i] = 1
        rows.append(row)
        meta.append(("sku", sku))
    return np.vstack(rows), pd.DataFrame(meta, columns=["level", "series"])


def projection(S: np.ndarray, W: np.ndarray) -> np.ndarray:
    """G = (S' W^-1 S)^-1 S' W^-1 for a positive-definite W."""
    W_inv = np.linalg.inv(W)
    return np.linalg.solve(S.T @ W_inv @ S, S.T @ W_inv)


def shrink_covariance(residuals: np.ndarray) -> tuple[np.ndarray, float]:
    """Schäfer-Strimmer shrinkage of the residual covariance toward its diagonal.

    ``residuals`` is (n_obs x n_series), assumed zero-mean (one-step errors).
    Returns the shrunk covariance and the shrinkage intensity lambda.
    """
    n = residuals.shape[0]
    cov = residuals.T @ residuals / n
    sd = np.sqrt(np.maximum(np.diag(cov), 1e-12))
    xs = residuals / sd
    corr = xs.T @ xs / n
    xs2 = xs ** 2
    var_corr = (xs2.T @ xs2 - (xs.T @ xs) ** 2 / n) / (n * (n - 1))
    np.fill_diagonal(var_corr, 0.0)
    off = corr - np.eye(len(sd))
    np.fill_diagonal(off, 0.0)
    lam = float(np.clip(var_corr.sum() / max((off ** 2).sum(), 1e-12), 0.0, 1.0))
    target = np.diag(np.diag(cov))
    return lam * target + (1 - lam) * cov, lam


def reconcile(method: str, y_hat: np.ndarray, S: np.ndarray, *, history_bottom: np.ndarray | None = None,
              residuals: np.ndarray | None = None) -> np.ndarray:
    """Return reconciled forecasts for all series (same order as ``S`` rows)."""
    n_bottom = S.shape[1]
    if method == "base":
        return y_hat
    if method == "bottom_up":
        return S @ y_hat[-n_bottom:]
    if method == "top_down":
        shares = history_bottom.sum(axis=1) / history_bottom.sum()   # historical proportions
        return S @ (y_hat[0] * shares)
    if method == "ols":
        G = projection(S, np.eye(S.shape[0]))
    elif method == "wls_structural":
        G = projection(S, np.diag(S.sum(axis=1)))
    elif method == "mint_shrink":
        W, _ = shrink_covariance(residuals)
        G = projection(S, W + 1e-9 * np.eye(len(W)))
    else:
        raise ValueError(f"unknown reconciliation method {method!r}")
    return S @ (G @ y_hat)


def coherence_gap(y: np.ndarray, S: np.ndarray) -> float:
    """Largest absolute gap between each series and the sum of its SKUs (0 = coherent)."""
    n_bottom = S.shape[1]
    return float(np.abs(S @ y[-n_bottom:] - y).max())
