"""Shared intensity-hazard disruption helpers (earthquake, landslide, winter storm)."""

from __future__ import annotations

import logging
from typing import Callable, Dict, Optional

import geopandas as gpd
import numpy as np
import pandas as pd

from resiflow.exposure.raster_line import (
    clip_features,
    intersect_features_with_raster,
    subset_features_to_raster_extent,
)

DAMAGE_LEVEL_DICT: Dict[str, int] = {
    "no": 0,
    "minor": 1,
    "moderate": 2,
    "extensive": 3,
    "severe": 4,
}
DAMAGE_LEVEL_DICT_REVERSE: Dict[int, str] = {v: k for k, v in DAMAGE_LEVEL_DICT.items()}


def intersections_with_intensity(
    road_links: gpd.GeoDataFrame,
    event_key: str,
    raster_path: str,
    clip_path: Optional[str],
    *,
    field_name: str,
    intensity_col: str,
    damage_level_col: str,
    categorical_fn: Callable[[pd.Series, pd.Series], pd.Series],
    boundary_gdf: Optional[gpd.GeoDataFrame] = None,
    script3_depth_scale: float = 1.0,
) -> gpd.GeoDataFrame | None:
    """Sample raster along links and attach intensity + categorical damage."""
    candidate_links = subset_features_to_raster_extent(road_links, raster_path)
    clipped_features = clip_features(candidate_links, clip_path, event_key, boundary_gdf)
    if clipped_features.empty:
        logging.info("Intensity hazard clip produced no features")
        return None

    intersections = intersect_features_with_raster(
        raster_path,
        event_key,
        clipped_features,
        field_name,
    )
    if intersections is None or intersections.empty:
        return intersections

    intersections = intersections.reset_index(drop=True)
    depth_col = f"flood_depth_{field_name}"
    if depth_col not in intersections.columns:
        intersections[depth_col] = 0.0
    intersections[intensity_col] = pd.to_numeric(intersections[depth_col], errors="coerce").fillna(0.0)
    intersections[damage_level_col] = categorical_fn(
        intersections["road_classification"],
        intersections[intensity_col],
    )
    intersections["flood_depth_surface"] = intersections[intensity_col] * script3_depth_scale
    intersections["flood_depth_river"] = 0.0
    intersections["damage_level_surface"] = intersections[damage_level_col]
    intersections["damage_level_river"] = "no"
    return intersections


def features_with_intensity(
    features: gpd.GeoDataFrame,
    intersections: gpd.GeoDataFrame,
    *,
    intensity_col: str,
    intensity_max_col: str,
    damage_level_col: str,
    script3_depth_scale: float = 1.0,
) -> gpd.GeoDataFrame:
    """Aggregate segment intensities to link-level fields."""
    intersections = intersections.copy()
    intersections[damage_level_col] = intersections[damage_level_col].map(DAMAGE_LEVEL_DICT)
    grouped = intersections.groupby("e_id", as_index=False).agg(
        {intensity_col: "max", damage_level_col: "max"}
    )
    grouped[damage_level_col] = (
        pd.to_numeric(grouped[damage_level_col], errors="coerce")
        .replace([np.inf, -np.inf], np.nan)
        .fillna(0)
        .astype(int)
        .map(DAMAGE_LEVEL_DICT_REVERSE)
    )
    features = features.merge(
        grouped[["e_id", intensity_col, damage_level_col]],
        how="left",
        on="e_id",
    )
    features[intensity_max_col] = features[intensity_col].fillna(0.0)
    features["damage_level_max"] = features[damage_level_col].fillna("no")
    features["flood_depth_max"] = features[intensity_max_col] * script3_depth_scale
    return features
