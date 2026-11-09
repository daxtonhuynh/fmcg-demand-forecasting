"""Small helpers for writing stage outputs inside this folder only."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import config


def stage_dir(stage: str, sub: str | None = None) -> Path:
    path = config.STAGE_DIRS[stage] / sub if sub else config.STAGE_DIRS[stage]
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_table(df: pd.DataFrame, stage: str, name: str, index: bool = False) -> Path:
    path = stage_dir(stage, "tables") / f"{name}.csv"
    df.to_csv(path, index=index, float_format="%.12g")
    return path


def figure_path(stage: str, name: str) -> Path:
    return stage_dir(stage, "figures") / f"{name}.png"


def _default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.ndarray,)):
        return o.tolist()
    if isinstance(o, (pd.Timestamp,)):
        return o.strftime("%Y-%m-%d")
    raise TypeError(f"not JSON serialisable: {type(o)}")


def save_json(obj, stage: str, name: str) -> Path:
    path = stage_dir(stage) / f"{name}.json"
    path.write_text(json.dumps(obj, indent=2, default=_default))
    return path


def load_json(stage: str, name: str):
    return json.loads((config.STAGE_DIRS[stage] / f"{name}.json").read_text())


def save_processed(df: pd.DataFrame, name: str) -> Path:
    config.PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    path = config.PROCESSED_DIR / f"{name}.parquet"
    df.to_parquet(path, index=False)
    return path


def load_processed(name: str) -> pd.DataFrame:
    return pd.read_parquet(config.PROCESSED_DIR / f"{name}.parquet")
