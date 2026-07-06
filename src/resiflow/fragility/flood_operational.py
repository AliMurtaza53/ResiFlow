"""Flood operational fragility: intensity to max_speed."""

from __future__ import annotations

import numpy as np
import pandas as pd


def compute_maximum_speed_on_flooded_roads(
    depth: float,
    free_flow_speed: float,
    threshold=30,
) -> float:
    """
    Calculates the maximum allowable speed on flooded roads based on flood depth.

    Parameters:
        depth (float): Flood depth in meters.
        free_flow_speed (float): Free-flow speed under normal conditions (mph).
        threshold (float, optional): Depth threshold in centimeters for road closure
            (default is 30 cm).

    Returns:
        float: Maximum speed on the flooded road in miles per hour (mph).
    """

    depth = depth * 100  # m to cm
    if depth < threshold:  # cm
        value = free_flow_speed * (depth / threshold - 1) ** 2  # mph
        return value  # mph
    else:
        return 0.0  # mph

def apply_max_speed_to_links(
    road_links: pd.DataFrame,
    *,
    depth_key: int,
    depth_col: str = "flood_depth_max",
    free_flow_col: str = "free_flow_speeds",
    out_col: str = "max_speed",
) -> pd.DataFrame:
    """Vectorized speed cap using the Script 2 closure rule (depth_key in cm)."""
    out = road_links.copy()
    if depth_col not in out.columns:
        out[depth_col] = 0.0
    out[depth_col] = out[depth_col].fillna(0.0)
    if free_flow_col not in out.columns:
        out[free_flow_col] = 50.0
    out[free_flow_col] = out[free_flow_col].fillna(50.0)
    flood_depth_cm = pd.to_numeric(out[depth_col], errors="coerce") * 100.0
    free_flow_speed = pd.to_numeric(out[free_flow_col], errors="coerce")
    out[out_col] = np.where(
        flood_depth_cm < depth_key,
        free_flow_speed * ((flood_depth_cm / depth_key - 1) ** 2),
        0.0,
    )
    return out
