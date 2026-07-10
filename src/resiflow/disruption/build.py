"""Build LinkDisruptionRecord rows from hazard + fragility outputs."""

from __future__ import annotations

import geopandas as gpd
import pandas as pd

from resiflow.disruption.flood import (
    DAMAGE_LEVEL_DICT,
    DAMAGE_LEVEL_DICT_REVERSE,
    features_with_damage,
)
from resiflow.disruption.earthquake import features_with_earthquake
from resiflow.disruption.landslide import features_with_landslide
from resiflow.disruption.link_record import (
    apply_legacy_flood_columns,
    apply_legacy_intensity_columns,
    apply_legacy_snow_columns,
)
from resiflow.fragility.earthquake_operational import apply_max_speed_to_links as apply_eq_max_speed
from resiflow.fragility.flood_operational import apply_max_speed_to_links
from resiflow.fragility.landslide_operational import apply_max_speed_to_links as apply_ls_max_speed
from resiflow.fragility.snow_operational import apply_max_speed_to_links as apply_snow_max_speed
from resiflow.hazards.base import HazardEvent
from resiflow.disruption.snow import (
    DAMAGE_LEVEL_DICT as SNOW_DAMAGE_LEVEL_DICT,
    DAMAGE_LEVEL_DICT_REVERSE as SNOW_DAMAGE_LEVEL_DICT_REVERSE,
    features_with_snow,
)


_BASE_SCENARIO_ASSIGNMENT_COLS = [
    "e_id",
    "combined_label",
    "assignment_tier",
    "network_class",
    "network_source",
    "damage_profile",
    "free_flow_speeds",
    "initial_flow_speeds",
    "min_flow_speeds",
    "current_capacity",
    "current_speed",
    "current_flow",
]

_ASSIGNMENT_STATE_COLS = [
    "combined_label",
    "assignment_tier",
    "network_class",
    "network_source",
    "damage_profile",
    "free_flow_speeds",
    "initial_flow_speeds",
    "min_flow_speeds",
    "current_capacity",
    "current_speed",
    "current_flow",
]


def build_flood_link_disruption(
    road_links: gpd.GeoDataFrame,
    intersections: gpd.GeoDataFrame,
    base_scenario_links: gpd.GeoDataFrame,
    *,
    hazard_event: HazardEvent,
    depth_key: int,
) -> gpd.GeoDataFrame:
    """Merge exposure + dual fragility into legacy-compatible road_links output."""
    links = features_with_damage(
        road_links,
        intersections,
        DAMAGE_LEVEL_DICT,
        DAMAGE_LEVEL_DICT_REVERSE,
    )

    cols_to_drop = [c for c in _ASSIGNMENT_STATE_COLS if c in links.columns]
    if cols_to_drop:
        links = links.drop(columns=cols_to_drop)

    merge_cols = [c for c in _BASE_SCENARIO_ASSIGNMENT_COLS if c in base_scenario_links.columns]
    links = links.merge(
        base_scenario_links[merge_cols],
        how="left",
        on="e_id",
    )
    links = links.loc[:, ~links.columns.duplicated()]

    if "flood_depth_max" not in links.columns:
        links["flood_depth_max"] = 0.0
    links["flood_depth_max"] = links["flood_depth_max"].fillna(0.0)
    links["free_flow_speeds"] = links["free_flow_speeds"].fillna(50.0)

    links = apply_max_speed_to_links(links, depth_key=depth_key)
    return apply_legacy_flood_columns(
        links,
        depth_key=depth_key,
        event_id=hazard_event.event_id,
    )


def build_snow_link_disruption(
    road_links: gpd.GeoDataFrame,
    intersections: gpd.GeoDataFrame,
    base_scenario_links: gpd.GeoDataFrame,
    *,
    hazard_event: HazardEvent,
    snow_key_mm: int,
) -> gpd.GeoDataFrame:
    """Merge snow exposure + dual fragility into legacy-compatible road_links output."""
    links = features_with_snow(
        road_links,
        intersections,
        SNOW_DAMAGE_LEVEL_DICT,
        SNOW_DAMAGE_LEVEL_DICT_REVERSE,
    )

    cols_to_drop = [c for c in _ASSIGNMENT_STATE_COLS + ["snow_depth_mm", "damage_level_snow"] if c in links.columns]
    if cols_to_drop:
        links = links.drop(columns=cols_to_drop)

    merge_cols = [c for c in _BASE_SCENARIO_ASSIGNMENT_COLS if c in base_scenario_links.columns]
    links = links.merge(
        base_scenario_links[merge_cols],
        how="left",
        on="e_id",
    )
    links = links.loc[:, ~links.columns.duplicated()]
    links["free_flow_speeds"] = links["free_flow_speeds"].fillna(50.0)

    links = apply_snow_max_speed(links, snow_key_mm=snow_key_mm)
    return apply_legacy_snow_columns(
        links,
        snow_key_mm=snow_key_mm,
        event_id=hazard_event.event_id,
    )


def build_earthquake_link_disruption(
    road_links: gpd.GeoDataFrame,
    intersections: gpd.GeoDataFrame,
    base_scenario_links: gpd.GeoDataFrame,
    *,
    hazard_event: HazardEvent,
    scenario_key: int,
) -> gpd.GeoDataFrame:
    links = features_with_earthquake(road_links, intersections)
    cols_to_drop = [c for c in _ASSIGNMENT_STATE_COLS if c in links.columns]
    if cols_to_drop:
        links = links.drop(columns=cols_to_drop)
    merge_cols = [c for c in _BASE_SCENARIO_ASSIGNMENT_COLS if c in base_scenario_links.columns]
    links = links.merge(base_scenario_links[merge_cols], how="left", on="e_id")
    links = links.loc[:, ~links.columns.duplicated()]
    links["free_flow_speeds"] = links["free_flow_speeds"].fillna(50.0)
    links = apply_eq_max_speed(links)
    out = apply_legacy_intensity_columns(
        links,
        hazard_type="earthquake",
        intensity_unit="g_pga",
        intensity_col="pga_max_g",
        scenario_param=scenario_key,
        event_id=hazard_event.event_id,
    )
    out["flood_depth_max"] = out["intensity_primary"] * 0.5
    return out


def build_landslide_link_disruption(
    road_links: gpd.GeoDataFrame,
    intersections: gpd.GeoDataFrame,
    base_scenario_links: gpd.GeoDataFrame,
    *,
    hazard_event: HazardEvent,
    scenario_key: int,
) -> gpd.GeoDataFrame:
    links = features_with_landslide(road_links, intersections)
    cols_to_drop = [c for c in _ASSIGNMENT_STATE_COLS if c in links.columns]
    if cols_to_drop:
        links = links.drop(columns=cols_to_drop)
    merge_cols = [c for c in _BASE_SCENARIO_ASSIGNMENT_COLS if c in base_scenario_links.columns]
    links = links.merge(base_scenario_links[merge_cols], how="left", on="e_id")
    links = links.loc[:, ~links.columns.duplicated()]
    links["free_flow_speeds"] = links["free_flow_speeds"].fillna(50.0)
    links = apply_ls_max_speed(links)
    out = apply_legacy_intensity_columns(
        links,
        hazard_type="landslide",
        intensity_unit="mm_displacement",
        intensity_col="landslide_max_mm",
        scenario_param=scenario_key,
        event_id=hazard_event.event_id,
    )
    out["flood_depth_max"] = out["landslide_max_mm"] / 1000.0
    return out


def build_winter_storm_link_disruption(
    road_links: gpd.GeoDataFrame,
    intersections: gpd.GeoDataFrame,
    base_scenario_links: gpd.GeoDataFrame,
    *,
    hazard_event: HazardEvent,
    scenario_key: int,
) -> gpd.GeoDataFrame:
    from resiflow.disruption.winter_storm import features_with_winter_storm
    from resiflow.fragility.winter_storm_operational import apply_max_speed_to_links as apply_ws_max_speed

    links = features_with_winter_storm(road_links, intersections)
    cols_to_drop = [c for c in _ASSIGNMENT_STATE_COLS if c in links.columns]
    if cols_to_drop:
        links = links.drop(columns=cols_to_drop)
    merge_cols = [c for c in _BASE_SCENARIO_ASSIGNMENT_COLS if c in base_scenario_links.columns]
    links = links.merge(base_scenario_links[merge_cols], how="left", on="e_id")
    links = links.loc[:, ~links.columns.duplicated()]
    links["free_flow_speeds"] = links["free_flow_speeds"].fillna(50.0)
    links = apply_ws_max_speed(links, ice_key_mm=int(scenario_key))
    out = apply_legacy_intensity_columns(
        links,
        hazard_type="winter_storm",
        intensity_unit="mm_ice",
        intensity_col="winter_storm_max_mm",
        scenario_param=scenario_key,
        event_id=hazard_event.event_id,
    )
    out["flood_depth_max"] = out["winter_storm_max_mm"] / 1000.0
    return out


def run_disruption(
    scenario_key: int,
    event_key: str,
    *,
    base_path=None,
    hazard_type: str | None = None,
    hazard_source=None,
) -> None:
    """Hazard-agnostic entry point; dispatches flood or snow pipelines."""
    import os
    from pathlib import Path

    resolved_type = (hazard_type or os.environ.get("RESIFLOW_HAZARD_TYPE", "flood")).strip().lower()

    if resolved_type == "snow":
        from resiflow.disruption.pipeline_snow import run_snow_disruption

        run_snow_disruption(
            scenario_key,
            event_key,
            base_path=base_path,
            hazard_source=hazard_source,
        )
        return

    if resolved_type == "earthquake":
        from resiflow.disruption.earthquake import intersections_with_earthquake
        from resiflow.disruption.pipeline_intensity import run_intensity_disruption
        from resiflow.hazards.sioux_falls_multihazard import EarthquakeHazardSource

        if base_path is None:
            from resiflow.utils import load_config

            base_path = Path(load_config()["paths"]["soge_clusters"])
        if hazard_source is None:
            from resiflow.utils import load_config

            hazard_source = EarthquakeHazardSource(Path(load_config()["paths"]["soge_clusters"]))
        run_intensity_disruption(
            scenario_key,
            event_key,
            hazard_label="earthquake",
            hazard_source=hazard_source,
            intersections_fn=intersections_with_earthquake,
            build_link_fn=build_earthquake_link_disruption,
            base_path=base_path,
        )
        return

    if resolved_type == "landslide":
        from resiflow.disruption.landslide import intersections_with_landslide
        from resiflow.disruption.pipeline_intensity import run_intensity_disruption
        from resiflow.hazards.sioux_falls_multihazard import LandslideHazardSource

        if base_path is None:
            from resiflow.utils import load_config

            base_path = Path(load_config()["paths"]["soge_clusters"])
        if hazard_source is None:
            from resiflow.utils import load_config

            hazard_source = LandslideHazardSource(Path(load_config()["paths"]["soge_clusters"]))
        run_intensity_disruption(
            scenario_key,
            event_key,
            hazard_label="landslide",
            hazard_source=hazard_source,
            intersections_fn=intersections_with_landslide,
            build_link_fn=build_landslide_link_disruption,
            base_path=base_path,
        )
        return

    if resolved_type == "winter_storm":
        from resiflow.disruption.pipeline_winter_storm import run_winter_storm_disruption

        run_winter_storm_disruption(
            scenario_key,
            event_key,
            base_path=base_path,
            hazard_source=hazard_source,
        )
        return

    from resiflow.disruption.pipeline import run_flood_disruption

    if hazard_source is None and base_path is None:
        from resiflow.utils import load_config

        base_path = Path(load_config()["paths"]["soge_clusters"])
    elif base_path is None:
        from resiflow.utils import load_config

        base_path = Path(load_config()["paths"]["soge_clusters"])
    else:
        base_path = Path(base_path)

    if hazard_source is None:
        from resiflow.hazards.sioux_falls_multihazard import resolve_multihazard_flood_source

        mh = resolve_multihazard_flood_source(base_path)
        if mh is not None:
            hazard_source = mh

    run_flood_disruption(
        scenario_key,
        event_key,
        base_path=base_path,
        hazard_source=hazard_source,
    )
