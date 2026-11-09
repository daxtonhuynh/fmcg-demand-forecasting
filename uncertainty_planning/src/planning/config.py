"""Every locked design choice for the uncertainty-aware planning extension.

This folder is a self-contained extension of the main FMCG forecasting project.
It only *reads* the raw dataset; it never writes outside ``uncertainty_planning/``.
"""
from __future__ import annotations

import os
from pathlib import Path

# --------------------------------------------------------------------------- paths
PROJECT_DIR = Path(__file__).resolve().parents[2]          # .../uncertainty_planning
RAW_FILENAME = "fmcg_sales_marketing_profitability_2023_2025.csv"


def raw_csv_path() -> Path:
    """Locate the raw dataset without copying it.

    Order: $FMCG_RAW_CSV, the main project's data/raw/, then a local data/raw/.
    """
    candidates = []
    if os.environ.get("FMCG_RAW_CSV"):
        candidates.append(Path(os.environ["FMCG_RAW_CSV"]))
    candidates += [
        PROJECT_DIR.parent / "data" / "raw" / RAW_FILENAME,
        PROJECT_DIR / "data" / "raw" / RAW_FILENAME,
    ]
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError(
        "Raw dataset not found. Put it at ../data/raw/ (main project), at "
        "uncertainty_planning/data/raw/, or set FMCG_RAW_CSV. Tried: "
        + ", ".join(str(p) for p in candidates)
    )


DATA_DIR = PROJECT_DIR / "data"
PROCESSED_DIR = DATA_DIR / "processed"
WAREHOUSE_PATH = DATA_DIR / "warehouse" / "planning.duckdb"
OUTPUT_DIR = PROJECT_DIR / "outputs"
SQL_DIR = PROJECT_DIR / "sql"
DASHBOARD_DIR = PROJECT_DIR / "dashboard"

STAGE_DIRS = {
    "p1": OUTPUT_DIR / "p1_data",
    "p2": OUTPUT_DIR / "p2_probabilistic",
    "p3": OUTPUT_DIR / "p3_hierarchy",
    "p4": OUTPUT_DIR / "p4_inventory",
    "p5": OUTPUT_DIR / "p5_information",
    "p6": OUTPUT_DIR / "p6_sql",
}

# ---------------------------------------------------------------- time design
TEST_YEAR = 2025                    # untouched test period
CALIBRATION_START = "2024-01"       # first forecast origin whose errors may calibrate intervals
SELECTION_PERIOD = ("2024-07", "2024-12")   # used to pick champions BEFORE looking at 2025
SIM_START = "2024-07"               # inventory simulation warm-up starts here; metrics use TEST_YEAR only
MIN_CALIBRATION_ERRORS = 60         # an interval is only issued with at least this many past errors

# ------------------------------------------------------------------ forecasts
FORECAST_METHODS = ["historical_average", "seasonal_naive", "naive", "moving_average_3"]
METHOD_LABELS = {
    "historical_average": "Historical average",
    "seasonal_naive": "Seasonal naive",
    "naive": "Naive (last month)",
    "moving_average_3": "Moving average (3m)",
    "level_best": "Best method per level",
}
WINDOWS = [1, 2, 3]                 # months summed: protection period = lead time + 1 review month

# ---------------------------------------------------------------- uncertainty
QUANTILE_METHODS = ["normal", "empirical", "empirical_scaled"]
QMETHOD_LABELS = {
    "normal": "Normal (pooled σ)",
    "empirical": "Empirical / conformal (pooled)",
    "empirical_scaled": "Empirical, scaled by SKU volatility",
}
EVAL_TAUS = [0.05, 0.10, 0.25, 0.50, 0.75, 0.80, 0.90, 0.95, 0.975, 0.99]
FAN_TAUS = [0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95]

# ------------------------------------------------------------------ hierarchy
HIERARCHY_LEVELS = ["total", "category", "brand", "sku"]
BASE_FORECAST_SETS = ["historical_average", "seasonal_naive", "level_best"]
RECONCILIATION_METHODS = ["base", "bottom_up", "top_down", "ols", "wls_structural", "mint_shrink"]

# ------------------------------------------------------------------ inventory
# Assumptions the dataset cannot supply; every result is reported with sensitivity.
LEAD_TIMES = [0, 1, 2]              # months between order and receipt
BASE_LEAD_TIME = 1
REVIEW_PERIOD = 1                   # months (fixed)
HOLDING_RATES = [0.15, 0.25, 0.35]  # annual holding cost as share of unit cost (COGS)
BASE_HOLDING_RATE = 0.25
LOST_SALE_BASES = ["profit", "gross_margin"]   # what a lost unit costs
BASE_LOST_SALE_BASIS = "profit"
SERVICE_TARGETS = [0.50, 0.80, 0.85, 0.90, 0.95, 0.97, 0.98, 0.99]
COVER_RULES = [0.25, 0.50, 0.75, 1.00]          # rule of thumb: safety stock = k months of forecast
CRITICAL_RATIO_BOUNDS = (0.50, 0.995)

# ------------------------------------------------------- value of information
LARGE_ORDER_QUANTILE = 0.90         # orders at or above this size (pre-test) count as "large"
VISIBILITY_LEVELS = [0.0, 0.25, 0.50, 0.75, 1.0]
N_SEEDS = 30
RANDOM_SEED = 42

# Simulated planner archetypes for Forecast Value Added (FVA)
PLANNER_ARCHETYPES = {
    "informed": {"label": "Informed (sees 50% of large orders)", "visibility": 0.5},
    "optimistic": {"label": "Optimistic (+20% on 30% of SKU-months)", "share": 0.30, "uplift": 0.20},
    "chaser": {"label": "Chaser (50/50 with last month)", "weight_last": 0.5},
    "sandbagger": {"label": "Sandbagger (-10% everywhere)", "cut": 0.10},
}
