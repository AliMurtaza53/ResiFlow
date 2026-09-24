"""Winter storm disruption aggregation."""

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
from resiflow.fragility.winter_storm_categorical import compute_damage_levels_vectorized
from resiflow.parameters import get_parameter

SCRIPT3_DEPTH_SCALE = get_parameter(
    "hazard_disruption", "winter_storm_script3_depth_scale", 0.001
)

_COMPANION_FIELDS = {
    # source_field -> (raster field_name, intensity_col)
    "duration_hours": ("duration_hours", "duration_hours"),
    "air_temp_F": ("air_temp_F", "air_temp_F"),
}


def _no_damage_level(
    road_classification: pd.Series, intensity: pd.Series, road_label: pd.Series
) -> pd.Series:
    """Placeholder categorical_fn for the duration_hours/air_temp_F passes --
    these are T32 cost-formula inputs (hazards/winter_storm_cost.py), not
    intensities to run through a fragility curve. See disruption/
    earthquake.py's identically-purposed _no_damage_level for the psa1p0/
    liquefaction_class companions this mirrors."""
    return pd.Series(["no"] * len(intensity), index=intensity.index)


def intersections_with_winter_storm(
    road_links: gpd.GeoDataFrame,
    event_key: str,
    raster_path: str,
    clip_path: Optional[str],
    boundary_gdf: Optional[gpd.GeoDataFrame] = None,
    *,
    source_field: Optional[str] = None,
) -> gpd.GeoDataFrame | None:
    if source_field in _COMPANION_FIELDS:
        field_name, intensity_col = _COMPANION_FIELDS[source_field]
        # air_temp_F: a nodata pixel filling to 0.0 (this project's usual
        # default) would silently read as "0 deg F", a real and very cold
        # value -- not "unknown" -- and would bias T32's T_factor upward
        # (winter_storm_cost.py's own missing-temperature fallback is
        # T_factor=1.0/no penalty, the opposite direction). NaN instead, so
        # a genuinely missing reading stays missing all the way to
        # hazus_bridge's row.get(). duration_hours keeps the 0.0 default:
        # "no active-snowfall day detected" is a real, intended reading
        # there, not a missing-data sentinel.
        fillna_value = float("nan") if source_field == "air_temp_F" else 0.0
        result = intersections_with_intensity(
            road_links,
            event_key,
            raster_path,
            clip_path,
            field_name=field_name,
            intensity_col=intensity_col,
            damage_level_col=f"_{source_field}_unused_damage_level",
            categorical_fn=_no_damage_level,
            boundary_gdf=boundary_gdf,
            fillna_value=fillna_value,
        )
        if result is None or result.empty:
            return result
        return result[["e_id", "length", "index_i", "index_j", intensity_col]]
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
