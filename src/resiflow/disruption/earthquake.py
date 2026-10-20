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
from resiflow.hazards.hazus_bridge import bridge_sa_damage_level_default
from resiflow.parameters import get_parameter

# Script 3 shim: map PGA (g) to pseudo-depth meters (PLACEHOLDER scaling).
SCRIPT3_DEPTH_SCALE = get_parameter(
    "hazard_disruption", "earthquake_script3_depth_scale", 0.5
)


def _no_damage_level(
    road_classification: pd.Series, intensity: pd.Series, road_label: pd.Series
) -> pd.Series:
    """Placeholder categorical_fn for companion raster passes (Sa / liquefaction).

    Sa(1.0s) bridge damage is applied in ``features_with_earthquake`` after the
    PGA+Sa merge (see that function), not here — this pass only carries
    ``psa1p0_g``. Accepts road_label for interface parity with
    ``intersections_with_intensity``.
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
    if source_field == "liquefaction_class":
        result = intersections_with_intensity(
            road_links,
            event_key,
            raster_path,
            clip_path,
            field_name="liquefaction_class",
            intensity_col="liquefaction_class_code",
            damage_level_col="_liquefaction_class_unused_damage_level",
            categorical_fn=_no_damage_level,
            boundary_gdf=boundary_gdf,
        )
        if result is None or result.empty:
            return result
        return result[["e_id", "length", "index_i", "index_j", "liquefaction_class_code"]]
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


def _is_bridge_mask(features: pd.DataFrame) -> pd.Series:
    """Bridge if road_label==bridge or road_bridge==yes (either column may exist)."""
    mask = pd.Series(False, index=features.index)
    if "road_label" in features.columns:
        mask = mask | features["road_label"].astype(str).str.strip().str.lower().eq(
            "bridge"
        )
    if "road_bridge" in features.columns:
        mask = mask | features["road_bridge"].astype(str).str.strip().str.lower().eq(
            "yes"
        )
    return mask


def features_with_earthquake(
    features: gpd.GeoDataFrame,
    intersections: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    """Aggregate PGA (+ optional Sa) and set bridge damage_level from Sa(1.0s).

    Pipeline order (see ``pipeline_intensity.run_intensity_disruption``):
      1. PGA pass writes ``pga_g`` + ``damage_level_earthquake`` (always ``no``).
      2. Sa pass writes ``psa1p0_g`` only (no damage column — avoids merge clash).
      3. Outer merge on (e_id, length, index_i, index_j) → both intensities
         present on the same intersection rows when both rasters exist.
      4. Here: aggregate PGA as usual; if ``psa1p0_g`` present, aggregate max Sa
         per link and override bridge ``damage_level_*`` via Table 7-6
         (``bridge_sa_damage_level_default``). Roads stay ``no`` from shaking.
    """
    out = features_with_intensity(
        features,
        intersections,
        intensity_col="pga_g",
        intensity_max_col="pga_max_g",
        damage_level_col="damage_level_earthquake",
        script3_depth_scale=SCRIPT3_DEPTH_SCALE,
    )

    if "psa1p0_g" not in intersections.columns:
        return out

    sa_grouped = (
        intersections.assign(
            _sa=pd.to_numeric(intersections["psa1p0_g"], errors="coerce")
        )
        .groupby("e_id", as_index=False)["_sa"]
        .max()
        .rename(columns={"_sa": "psa1p0_g"})
    )
    out = out.drop(columns=["psa1p0_g"], errors="ignore")
    out = out.merge(sa_grouped, how="left", on="e_id")
    out["psa1p0_g"] = pd.to_numeric(out["psa1p0_g"], errors="coerce").fillna(0.0)

    bridges = _is_bridge_mask(out)
    if not bridges.any():
        return out

    bridge_levels = [
        bridge_sa_damage_level_default(float(sa))
        for sa in out.loc[bridges, "psa1p0_g"].tolist()
    ]
    out.loc[bridges, "damage_level_earthquake"] = bridge_levels
    out.loc[bridges, "damage_level_max"] = bridge_levels
    return out


__all__ = [
    "DAMAGE_LEVEL_DICT",
    "DAMAGE_LEVEL_DICT_REVERSE",
    "features_with_earthquake",
    "intersections_with_earthquake",
]
