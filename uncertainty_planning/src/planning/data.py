"""Load the raw orders and build the SKU-month demand panel used by every stage."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import config

REQUIRED_COLUMNS = [
    "Order_ID", "Order_Date", "Customer_Type", "Product_Category", "Brand",
    "Product_Name", "SKU", "Units_Sold", "COGS_USD", "Net_Revenue_USD", "Profit_USD",
]


def load_orders(path=None) -> pd.DataFrame:
    """Read the raw CSV, check it, and add a month-start column."""
    path = path or config.raw_csv_path()
    orders = pd.read_csv(path, parse_dates=["Order_Date"])
    missing = [c for c in REQUIRED_COLUMNS if c not in orders.columns]
    if missing:
        raise ValueError(f"Raw file is missing columns: {missing}")
    problems = {
        "null values": int(orders[REQUIRED_COLUMNS].isna().sum().sum()),
        "duplicate order ids": int(orders["Order_ID"].duplicated().sum()),
        "non-positive units": int((orders["Units_Sold"] <= 0).sum()),
    }
    if any(problems.values()):
        raise ValueError(f"Raw data failed basic checks: {problems}")
    orders["month"] = orders["Order_Date"].dt.to_period("M").dt.to_timestamp()
    return orders


@dataclass
class Panel:
    """Units per SKU per month, with the attributes every stage needs.

    ``X[i, t]`` is the demand of ``skus[i]`` in ``months[t]``. Months are a full,
    gap-free monthly calendar so index arithmetic (t - 12, t + lead time) is safe.
    """

    months: list
    skus: list
    X: np.ndarray
    attrs: pd.DataFrame
    large_threshold: float = np.nan
    X_large: np.ndarray | None = None
    extra: dict = field(default_factory=dict)

    @property
    def n_months(self) -> int:
        return len(self.months)

    def idx(self, month) -> int:
        return self.months.index(pd.Timestamp(month))

    def year_idx(self, year: int) -> list[int]:
        return [i for i, m in enumerate(self.months) if m.year == year]

    @property
    def X_base(self) -> np.ndarray:
        return self.X - self.X_large


def pivot_units(orders: pd.DataFrame, skus, months) -> np.ndarray:
    wide = orders.pivot_table(index="SKU", columns="month", values="Units_Sold", aggfunc="sum")
    return wide.reindex(index=skus, columns=months).fillna(0.0).to_numpy(dtype=float)


def sku_attributes(orders: pd.DataFrame) -> pd.DataFrame:
    """Static SKU attributes and per-unit economics (medians are robust to bulk-order mix)."""
    per_unit = orders.assign(
        unit_price=orders["Net_Revenue_USD"] / orders["Units_Sold"],
        unit_cost=orders["COGS_USD"] / orders["Units_Sold"],
        unit_profit=orders["Profit_USD"] / orders["Units_Sold"],
    )
    attrs = per_unit.groupby("SKU").agg(
        product_name=("Product_Name", "first"),
        brand=("Brand", "first"),
        category=("Product_Category", "first"),
        unit_price=("unit_price", "median"),
        unit_cost=("unit_cost", "median"),
        unit_profit=("unit_profit", "median"),
        revenue=("Net_Revenue_USD", "sum"),
        units=("Units_Sold", "sum"),
    )
    attrs["unit_gross_margin"] = attrs["unit_price"] - attrs["unit_cost"]
    # ABC on cumulative revenue share: same rule as the main project's SQL query q6
    attrs = attrs.sort_values("revenue", ascending=False)
    share = 100 * attrs["revenue"].cumsum() / attrs["revenue"].sum()
    attrs["abc_class"] = np.select([share <= 80, share <= 95], ["A", "B"], "C")
    return attrs.sort_index()


def build_panel(orders: pd.DataFrame | None = None) -> Panel:
    orders = load_orders() if orders is None else orders
    months = list(pd.date_range(orders["month"].min(), orders["month"].max(), freq="MS"))
    attrs = sku_attributes(orders)
    skus = list(attrs.index)
    X = pivot_units(orders, skus, months)

    # "Large" orders are defined only from data known before the test year
    pre_test = orders["Order_Date"].dt.year < config.TEST_YEAR
    threshold = float(orders.loc[pre_test, "Units_Sold"].quantile(config.LARGE_ORDER_QUANTILE))
    large = orders["Units_Sold"] >= threshold
    X_large = pivot_units(orders[large], skus, months)

    panel = Panel(months=months, skus=skus, X=X, attrs=attrs,
                  large_threshold=threshold, X_large=X_large)
    panel.extra["large_orders"] = orders.loc[large, ["Order_ID", "SKU", "month", "Units_Sold", "Customer_Type"]]
    return panel


def panel_long(panel: Panel) -> pd.DataFrame:
    """Tidy SKU-month table (demand split into base and large orders)."""
    rows = []
    for i, sku in enumerate(panel.skus):
        for t, month in enumerate(panel.months):
            rows.append((sku, month, panel.X[i, t], panel.X_large[i, t]))
    out = pd.DataFrame(rows, columns=["sku", "month", "units", "large_units"])
    out["base_units"] = out["units"] - out["large_units"]
    return out
