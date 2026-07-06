"""Exposure sampling helpers behind the hazard-agnostic interface."""

from __future__ import annotations

import geopandas as gpd
import pandas as pd

from resiflow.disruption.flood import intersections_with_damage
from resiflow.exposure.raster_line import load_analysis_boundary
from resiflow.hazards.base import HazardEvent


def sample_link_intensity(
    links: gpd.GeoDataFrame,
    hazard_event: HazardEvent,
    *,
    flood_type: str,
    raster_path: str,
    clip_path: str | None,
    base_path,
    agg: str = "max",
) -> gpd.GeoDataFrame:
    """Sample per-segment intensity for one hazard field (flood implementation)."""
    boundary = load_analysis_boundary(base_path)
    intersections = intersections_with_damage(
        links,
        hazard_event.event_id,
        flood_type,
        raster_path,
        clip_path,
        boundary,
    )
    if intersections is None or intersections.empty:
        return pd.DataFrame(columns=["e_id", f"intensity_{flood_type}"])

    depth_col = f"flood_depth_{flood_type}"
    if depth_col not in intersections.columns:
        return pd.DataFrame(columns=["e_id", f"intensity_{flood_type}"])

    grouped = intersections.groupby("e_id", as_index=False)[depth_col].agg(agg)
    grouped = grouped.rename(columns={depth_col: f"intensity_{flood_type}"})
    return grouped
