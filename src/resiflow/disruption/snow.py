"""Snow disruption: exposure + fragility aggregation onto links."""

from __future__ import annotations

import logging
import sys
from typing import Dict, Optional

import geopandas as gpd
import numpy as np
import pandas as pd

from resiflow.exposure.raster_line import (
    clip_features,
    intersect_features_with_raster,
    subset_features_to_raster_extent,
)
from resiflow.fragility.snow_categorical import compute_damage_levels_vectorized

DAMAGE_LEVEL_DICT: Dict[str, int] = {
    "no": 0,
    "minor": 1,
    "moderate": 2,
    "extensive": 3,
    "severe": 4,
}
DAMAGE_LEVEL_DICT_REVERSE: Dict[int, str] = {v: k for k, v in DAMAGE_LEVEL_DICT.items()}


def intersections_with_snow(
    road_links: gpd.GeoDataFrame,
    event_key: str,
    snow_path: str,
    clip_path: Optional[str],
    boundary_gdf: Optional[gpd.GeoDataFrame] = None,
) -> gpd.GeoDataFrame:
    """Sample snow depth raster along links and attach categorical damage."""
    candidate_links = subset_features_to_raster_extent(road_links, snow_path)
    clipped_features = clip_features(candidate_links, clip_path, event_key, boundary_gdf)
    if clipped_features.empty:
        logging.info("Warning: snow clip features is empty")
        return None

    intersections = intersect_features_with_raster(
        snow_path,
        event_key,
        clipped_features,
        "snow",
    )
    if intersections is None or intersections.empty:
        return intersections

    intersections.reset_index(drop=True, inplace=True)
    depth_col = "flood_depth_snow"
    if depth_col not in intersections.columns:
        logging.warning("Snow raster intersection missing %s", depth_col)
        intersections[depth_col] = 0.0

    intersections["snow_depth_mm"] = pd.to_numeric(intersections[depth_col], errors="coerce").fillna(0.0)
    intersections["damage_level_snow"] = compute_damage_levels_vectorized(
        intersections["road_classification"],
        intersections["snow_depth_mm"],
    )
    # Script 3 compatibility: express snow as surface depth in meters.
    intersections["flood_depth_surface"] = intersections["snow_depth_mm"] / 1000.0
    intersections["flood_depth_river"] = 0.0
    intersections["damage_level_surface"] = intersections["damage_level_snow"]
    intersections["damage_level_river"] = "no"
    return intersections


def features_with_snow(
    features: gpd.GeoDataFrame,
    intersections: gpd.GeoDataFrame,
    damage_level_dict: Dict,
    damage_level_dict_reverse: Dict,
) -> gpd.GeoDataFrame:
    """Aggregate snow intersections to link-level disruption fields."""
    if "snow_depth_mm" not in intersections.columns:
        logging.info("Error: snow_depth_mm column is missing!")
        sys.exit(1)

    intersections = intersections.copy()
    intersections["damage_level_snow"] = intersections["damage_level_snow"].map(damage_level_dict)
    intersections_gp = intersections.groupby("e_id", as_index=False).agg(
        {"snow_depth_mm": "max", "damage_level_snow": "max"}
    )
    intersections_gp["damage_level_snow"] = (
        pd.to_numeric(intersections_gp["damage_level_snow"], errors="coerce")
        .replace([np.inf, -np.inf], np.nan)
        .fillna(0)
        .astype(int)
        .map(damage_level_dict_reverse)
    )

    features = features.merge(
        intersections_gp[["e_id", "snow_depth_mm", "damage_level_snow"]],
        how="left",
        on="e_id",
    )
    features["snow_depth_max_mm"] = features["snow_depth_mm"].fillna(0.0)
    features["damage_level_max"] = features["damage_level_snow"].fillna("no")
    features["flood_depth_max"] = features["snow_depth_max_mm"] / 1000.0
    return features
