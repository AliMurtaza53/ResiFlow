"""Earthquake disruption aggregation."""

from __future__ import annotations

from typing import Optional

import geopandas as gpd
import pandas as pd

from resiflow.disruption.intensity_hazard import (
    DAMAGE_LEVEL_DICT,
    DAMAGE_LEVEL_DICT_REVERSE,
    features_with_intensity,
    intersections_with_intensity,
)
from resiflow.fragility.earthquake_categorical import compute_damage_levels_vectorized
from resiflow.parameters import get_parameter

# Script 3 shim: map PGA (g) to pseudo-depth meters (PLACEHOLDER scaling).
SCRIPT3_DEPTH_SCALE = get_parameter(
    "hazard_disruption", "earthquake_script3_depth_scale", 0.5
)


def _no_damage_level(road_classification: pd.Series, intensity: pd.Series) -> pd.Series:
    """Placeholder categorical_fn for the Sa(1.0s) pass -- not a fragility model.

    HAZUS's own bridge fragility (hazards/hazus_bridge.py) computes damage
    state from Sa(1.0s)+PGD directly in Script 3; this raster-intersection
    pass only needs the raw intensity value carried through, so the categorical
    damage_level column intersections_with_intensity() also produces here is
    discarded before returning (see intersections_with_earthquake below).
    """
    return pd.Series(["no"] * len(intensity), index=intensity.index)


def intersections_with_earthquake(
    road_links: gpd.GeoDataFrame,
    event_key: str,
    raster_path: str,
    clip_path: Optional[str],
    boundary_gdf: Optional[gpd.GeoDataFrame] = None,
    *,
    source_field: Optional[str] = None,
) -> gpd.GeoDataFrame | None:
    if source_field == "psa1p0":
        # HAZUS bridge ground-shaking fragility (Table 7-6) needs Sa(1.0s),
        # not PGA -- a second, independent raster pass over the same links.
        # Only the raw intensity column is kept: this pass's own flood_depth_*/
        # damage_level_* columns are throwaway placeholders (see
        # _no_damage_level) and must NOT be merged alongside the real PGA
        # pass's columns of the same name in pipeline_intensity.py's outer
        # merge, or they'd silently collide/overwrite.
        result = intersections_with_intensity(
            road_links,
            event_key,
            raster_path,
            clip_path,
            field_name="psa1p0",
            intensity_col="psa1p0_g",
            damage_level_col="_psa1p0_unused_damage_level",
            categorical_fn=_no_damage_level,
            boundary_gdf=boundary_gdf,
        )
        if result is None or result.empty:
            return result
        return result[["e_id", "length", "index_i", "index_j", "psa1p0_g"]]
    return intersections_with_intensity(
        road_links,
        event_key,
        raster_path,
        clip_path,
        field_name="pga",
        intensity_col="pga_g",
        damage_level_col="damage_level_earthquake",
        categorical_fn=compute_damage_levels_vectorized,
        boundary_gdf=boundary_gdf,
        script3_depth_scale=SCRIPT3_DEPTH_SCALE,
    )


def features_with_earthquake(
    features: gpd.GeoDataFrame,
    intersections: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    return features_with_intensity(
        features,
        intersections,
        intensity_col="pga_g",
        intensity_max_col="pga_max_g",
        damage_level_col="damage_level_earthquake",
        script3_depth_scale=SCRIPT3_DEPTH_SCALE,
    )


__all__ = [
    "DAMAGE_LEVEL_DICT",
    "DAMAGE_LEVEL_DICT_REVERSE",
    "features_with_earthquake",
    "intersections_with_earthquake",
]
