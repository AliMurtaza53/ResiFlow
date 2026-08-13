"""Winter storm disruption aggregation."""

from __future__ import annotations

from typing import Optional

import geopandas as gpd

from resiflow.disruption.intensity_hazard import (
    DAMAGE_LEVEL_DICT,
    DAMAGE_LEVEL_DICT_REVERSE,
    features_with_intensity,
    intersections_with_intensity,
)
from resiflow.fragility.winter_storm_categorical import compute_damage_levels_vectorized
from resiflow.parameters import get_parameter

SCRIPT3_DEPTH_SCALE = get_parameter(
    "hazard_disruption", "winter_storm_script3_depth_scale", 0.001
)


def intersections_with_winter_storm(
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
        field_name="winter_storm",
        intensity_col="winter_storm_mm",
        damage_level_col="damage_level_winter_storm",
        categorical_fn=compute_damage_levels_vectorized,
        boundary_gdf=boundary_gdf,
        script3_depth_scale=SCRIPT3_DEPTH_SCALE,
    )


def features_with_winter_storm(
    features: gpd.GeoDataFrame,
    intersections: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    return features_with_intensity(
        features,
        intersections,
        intensity_col="winter_storm_mm",
        intensity_max_col="winter_storm_max_mm",
        damage_level_col="damage_level_winter_storm",
        script3_depth_scale=SCRIPT3_DEPTH_SCALE,
    )


__all__ = [
    "DAMAGE_LEVEL_DICT",
    "DAMAGE_LEVEL_DICT_REVERSE",
    "features_with_winter_storm",
    "intersections_with_winter_storm",
]
