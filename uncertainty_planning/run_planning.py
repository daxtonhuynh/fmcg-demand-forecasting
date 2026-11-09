"""Run the uncertainty-aware planning pipeline (stages P1-P7) in order.

    python run_planning.py          # all stages, about 1 minute
    python run_planning.py p4 p6    # only selected stages (later stages read earlier outputs)

Reads the raw dataset from ../data/raw/ (the main project), uncertainty_planning/data/raw/,
or $FMCG_RAW_CSV. Writes only inside this folder.
"""
from __future__ import annotations

import importlib
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "pipeline"))
sys.path.insert(0, str(HERE / "src"))

STAGES = {
    "p1": ("p1_data", "Demand panel, unit economics, large-order split"),
    "p2": ("p2_probabilistic", "Probabilistic forecasts and calibration"),
    "p3": ("p3_hierarchy", "Hierarchical reconciliation"),
    "p4": ("p4_inventory", "Inventory policy simulation and costing"),
    "p5": ("p5_information", "Value of information and planner FVA"),
    "p6": ("p6_warehouse", "DuckDB warehouse, checks, queries, reconciliation"),
    "p7": ("p7_dashboard_data", "Dashboard data"),
}


def main(selected: list[str]) -> None:
    unknown = [s for s in selected if s not in STAGES]
    if unknown:
        raise SystemExit(f"Unknown stage(s) {unknown}. Choose from {list(STAGES)}.")
    start = time.time()
    for key in selected or list(STAGES):
        module, title = STAGES[key]
        t0 = time.time()
        print(f"--- {key.upper()} {title}")
        importlib.import_module(module).run()
        print(f"    done in {time.time() - t0:.1f}s")
    print(f"Pipeline finished in {time.time() - start:.1f}s")


if __name__ == "__main__":
    main(sys.argv[1:])
