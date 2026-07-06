"""Snow operational fragility: snowfall depth (mm) to max_speed."""

from __future__ import annotations

import numpy as np
import pandas as pd


def apply_max_speed_to_links(
    road_links: pd.DataFrame,
    *,
    snow_key_mm: int,
    depth_col: str = "snow_depth_max_mm",
    free_flow_col: str = "free_flow_speeds",
    out_col: str = "max_speed",
) -> pd.DataFrame:
    """Vectorized speed cap from snow depth (mm) using the flood-style closure curve."""
    out = road_links.copy()
    if depth_col not in out.columns:
        out[depth_col] = 0.0
    out[depth_col] = pd.to_numeric(out[depth_col], errors="coerce").fillna(0.0)
    if free_flow_col not in out.columns:
        out[free_flow_col] = 50.0
    out[free_flow_col] = pd.to_numeric(out[free_flow_col], errors="coerce").fillna(50.0)
    snow_depth = out[depth_col]
    free_flow_speed = out[free_flow_col]
    out[out_col] = np.where(
        snow_depth < snow_key_mm,
        free_flow_speed * ((snow_depth / snow_key_mm - 1) ** 2),
        0.0,
    )
    return out
