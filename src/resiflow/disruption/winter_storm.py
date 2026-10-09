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
    # optional parallel rate-based estimate (hazards/winter_storm_rate.py); never drives max_speed
    "snowfall_rate_swe_in_hr": ("snowfall_rate_swe_in_hr", "snowfall_rate_swe_in_hr"),
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
        # snowfall_rate_swe_in_hr likewise stays NaN where the raster has no data (0.0 would
        # read as a real "no new snow" rate).
        fillna_value = float("nan") if source_field in ("air_temp_F", "snowfall_rate_swe_in_hr") else 0.0
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


def classify_merged_intersections(
    intersections: pd.DataFrame,
    road_links: pd.DataFrame,
) -> pd.DataFrame:
    """Re-classify segment damage levels once the companion rasters are merged in.

    ``intersections_with_winter_storm``'s categorical_fn only sees depth (each
    raster is intersected in its own pass), so the levels it writes are the
    depth-only BASE tier. Duration and temperature arrive as separate passes and
    are only joined afterwards, so the gated escalators
    (fragility/winter_storm_categorical.py) have to run here, on the merged
    segment rows. Script 3/4 read these segment-level levels
    (``damage_level_surface``), so this is where the real classification lands.

    Links whose FAF5 class is 41 (ferry) or 50 (centroid connector) never carry a
    damage level.
    """
    from resiflow.hazards.winter_storm_clearance import EXCLUDED_CLASSES

    out = intersections.copy()
    depth = pd.to_numeric(out.get("winter_storm_mm", 0.0), errors="coerce").fillna(0.0)
    levels = compute_damage_levels_vectorized(
        out["road_classification"] if "road_classification" in out.columns else pd.Series("", index=out.index),
        depth,
        None,
        duration_hours=out["duration_hours"] if "duration_hours" in out.columns else None,
        air_temp_f=out["air_temp_F"] if "air_temp_F" in out.columns else None,
    )
    if "faf5_class" in road_links.columns:
        excluded_ids = set(road_links.loc[road_links["faf5_class"].isin(EXCLUDED_CLASSES), "e_id"].astype(str))
        levels = levels.where(~out["e_id"].astype(str).isin(excluded_ids), "no")
    out["damage_level_winter_storm"] = levels
    out["damage_level_surface"] = levels
    return out


def features_with_winter_storm(
    features: gpd.GeoDataFrame,
    intersections: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    out = features_with_intensity(
        features,
        intersections,
        intensity_col="winter_storm_mm",
        intensity_max_col="winter_storm_max_mm",
        damage_level_col="damage_level_winter_storm",
        script3_depth_scale=SCRIPT3_DEPTH_SCALE,
    )
    # Audit columns for the escalators: worst case per link (longest duration,
    # coldest temperature) -- the same "worst segment" aggregation depth uses.
    for src, agg, dst in (
        ("duration_hours", "max", "duration_hours_max"),
        ("air_temp_F", "min", "air_temp_F_min"),
        ("snowfall_rate_swe_in_hr", "max", "snowfall_rate_swe_in_hr_max"),
    ):
        if src in intersections.columns:
            per_link = intersections.groupby("e_id")[src].agg(agg).rename(dst)
            out = out.merge(per_link, how="left", left_on="e_id", right_index=True)
    return out


__all__ = [
    "DAMAGE_LEVEL_DICT",
    "DAMAGE_LEVEL_DICT_REVERSE",
    "features_with_winter_storm",
    "intersections_with_winter_storm",
]
