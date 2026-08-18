"""Landslide disruption aggregation."""

from __future__ import annotations

from typing import Optional

import geopandas as gpd

from resiflow.disruption.intensity_hazard import (
    DAMAGE_LEVEL_DICT,
    DAMAGE_LEVEL_DICT_REVERSE,
    features_with_intensity,
    intersections_with_intensity,
)
from resiflow.fragility.landslide_categorical import compute_damage_levels_vectorized
from resiflow.parameters import get_parameter

SCRIPT3_DEPTH_SCALE = get_parameter(
    "hazard_disruption", "landslide_script3_depth_scale", 0.001
)  # mm → meters for Script 3 surface depth column


def intersections_with_landslide(
    road_links: gpd.GeoDataFrame,
    event_key: str,
    raster_path: str,
    clip_path: Optional[str],
    boundary_gdf: Optional[gpd.GeoDataFrame] = None,
) -> gpd.GeoDataFrame | None:
    return intersections_with_intensity(
        road_links,
        event_key,
        raster_path,
        clip_path,
        field_name="landslide",
        intensity_col="landslide_mm",
        damage_level_col="damage_level_landslide",
        categorical_fn=compute_damage_levels_vectorized,
        boundary_gdf=boundary_gdf,
        script3_depth_scale=SCRIPT3_DEPTH_SCALE,
    )


def features_with_landslide(
    features: gpd.GeoDataFrame,
    intersections: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    return features_with_intensity(
        features,
        intersections,
        intensity_col="landslide_mm",
        intensity_max_col="landslide_max_mm",
        damage_level_col="damage_level_landslide",
        script3_depth_scale=SCRIPT3_DEPTH_SCALE,
    )


__all__ = [
    "DAMAGE_LEVEL_DICT",
    "DAMAGE_LEVEL_DICT_REVERSE",
    "features_with_landslide",
    "intersections_with_landslide",
]
