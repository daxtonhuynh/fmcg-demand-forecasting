"""Periodic-review, order-up-to inventory simulation with lead time and lost sales.

Each month ``t`` (one review per month):

1. receive orders due this month;
2. inventory position = on hand + orders still in transit;
3. order ``max(0, S_t - position)``; it arrives at the start of month ``t + L``
   (with ``L = 0`` it is available immediately);
4. demand arrives; unmet demand is lost (no backorders).

The order-up-to level ``S_t`` covers the *protection period* ``L + 1`` months, so
it is the ``tau`` quantile of demand summed over months ``t .. t + L``. Stock left
at month end carries over. All quantities are units; money is applied afterwards
from per-unit economics, so one simulation serves every cost assumption.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import config


@dataclass
class SimResult:
    months: list            # simulated month indices
    opening: np.ndarray     # on hand before receipts (series x months)
    receipts: np.ndarray
    order_qty: np.ndarray
    demand: np.ndarray
    sales: np.ndarray
    lost: np.ndarray
    closing: np.ndarray
    order_up_to: np.ndarray
    final_on_hand: np.ndarray
    in_transit: np.ndarray  # arrivals scheduled after the last simulated month (series x L)

    @property
    def avg_on_hand(self) -> np.ndarray:
        return (self.opening + self.receipts + self.closing) / 2


def simulate(D: np.ndarray, order_up_to: np.ndarray, lead_time: int, start: int, end: int) -> SimResult:
    """Run the policy for months ``start .. end - 1``.

    ``order_up_to[:, t]`` must be filled for every simulated month. The system
    starts with on-hand stock equal to the first order-up-to level and nothing in
    transit; a warm-up period before the evaluation year absorbs that choice.
    """
    n, T = D.shape[0], end - start
    arrivals = np.zeros((n, end + lead_time + 1))
    on_hand = order_up_to[:, start].astype(float).copy()
    rec = {k: np.zeros((n, T)) for k in ["opening", "receipts", "order_qty", "sales", "lost", "closing", "S"]}
    for j, t in enumerate(range(start, end)):
        rec["opening"][:, j] = on_hand
        receipts = arrivals[:, t].copy()
        on_hand = on_hand + receipts
        in_transit = arrivals[:, t + 1:t + lead_time].sum(axis=1) if lead_time > 1 else 0.0
        q = np.maximum(order_up_to[:, t] - (on_hand + in_transit), 0.0)
        if lead_time == 0:
            on_hand = on_hand + q
            receipts = receipts + q
        else:
            arrivals[:, t + lead_time] += q
        sales = np.minimum(on_hand, D[:, t])
        on_hand = on_hand - sales
        rec["receipts"][:, j], rec["order_qty"][:, j] = receipts, q
        rec["sales"][:, j], rec["lost"][:, j] = sales, D[:, t] - sales
        rec["closing"][:, j], rec["S"][:, j] = on_hand, order_up_to[:, t]
    return SimResult(
        months=list(range(start, end)), opening=rec["opening"], receipts=rec["receipts"],
        order_qty=rec["order_qty"], demand=D[:, start:end].astype(float), sales=rec["sales"],
        lost=rec["lost"], closing=rec["closing"], order_up_to=rec["S"], final_on_hand=on_hand,
        in_transit=arrivals[:, end:end + lead_time].copy(),
    )


# --------------------------------------------------------------- economics
def unit_economics(attrs: pd.DataFrame, holding_rate: float, basis: str) -> tuple[np.ndarray, np.ndarray]:
    """(holding cost per unit-month, cost of one lost unit)."""
    holding = attrs["unit_cost"].to_numpy() * holding_rate / 12
    lost_col = {"profit": "unit_profit", "gross_margin": "unit_gross_margin"}[basis]
    lost = np.maximum(attrs[lost_col].to_numpy(), 0.0)
    return holding, lost


def critical_ratio(attrs: pd.DataFrame, holding_rate: float, basis: str) -> np.ndarray:
    """Cost-optimal cycle service level per SKU: underage / (underage + overage).

    Underage = value lost on one unit of unmet demand; overage = holding one
    unit for one review period (it carries over, so it is not written off).
    """
    holding, lost = unit_economics(attrs, holding_rate, basis)
    lo, hi = config.CRITICAL_RATIO_BOUNDS
    return np.clip(lost / (lost + holding), lo, hi)


QUANTITY_FIELDS = ["demand", "sales", "lost", "stockout_months", "avg_on_hand", "orders", "months"]


def quantities(result: SimResult, eval_months: list[int]) -> pd.DataFrame:
    """Cost-free per-series totals over the evaluation months."""
    cols = [result.months.index(m) for m in eval_months]
    avg = result.avg_on_hand[:, cols]
    return pd.DataFrame({
        "demand": result.demand[:, cols].sum(1),
        "sales": result.sales[:, cols].sum(1),
        "lost": result.lost[:, cols].sum(1),
        "stockout_months": (result.lost[:, cols] > 1e-9).sum(1),
        "avg_on_hand": avg.mean(1),                 # units, averaged over months
        "orders": (result.order_qty[:, cols] > 1e-9).sum(1),
        "months": len(cols),
    })


def add_costs(q: pd.DataFrame, attrs: pd.DataFrame, holding_rate: float, basis: str) -> pd.DataFrame:
    """Money view of per-series quantities (q indexed like attrs)."""
    holding, lost = unit_economics(attrs.loc[q.index], holding_rate, basis)
    unit_cost = attrs.loc[q.index, "unit_cost"].to_numpy()
    out = q.copy()
    out["inventory_value"] = q["avg_on_hand"] * unit_cost
    out["holding_cost"] = q["avg_on_hand"] * holding * q["months"]
    out["lost_value"] = q["lost"] * lost
    out["total_cost"] = out["holding_cost"] + out["lost_value"]
    return out


def summarize(q_costed: pd.DataFrame) -> dict:
    """Portfolio totals: service and money over the evaluation year."""
    d = q_costed
    return {
        "fill_rate": float(d["sales"].sum() / d["demand"].sum()),
        "cycle_service_level": float(1 - d["stockout_months"].sum() / d["months"].sum()),
        "avg_inventory_value": float(d["inventory_value"].sum()),
        "holding_cost": float(d["holding_cost"].sum()),
        "lost_value": float(d["lost_value"].sum()),
        "total_cost": float(d["total_cost"].sum()),
        "lost_units": float(d["lost"].sum()),
        "orders": float(d["orders"].sum()),
    }
