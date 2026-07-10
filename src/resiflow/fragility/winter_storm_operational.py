"""Winter storm operational fragility: quadratic ice-depth penalty (mm)."""

from __future__ import annotations

import numpy as np
import pandas as pd


def apply_max_speed_to_links(
    road_links: pd.DataFrame,
    *,
    ice_key_mm: int,
    depth_col: str = "winter_storm_max_mm",
    free_flow_col: str = "free_flow_speeds",
    out_col: str = "max_speed",
) -> pd.DataFrame:
    out = road_links.copy()
    if depth_col not in out.columns:
        out[depth_col] = 0.0
    depth = pd.to_numeric(out[depth_col], errors="coerce").fillna(0.0)
    free_flow = pd.to_numeric(out.get(free_flow_col, 50.0), errors="coerce").fillna(50.0)
    threshold = float(ice_key_mm)
    out[out_col] = np.where(
        depth < threshold,
        free_flow * ((depth / threshold - 1) ** 2),
        0.0,
    )
    return out
