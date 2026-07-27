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
from resiflow.hazards.scenario_registry import HazardScenario
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
    scenario_param: int,
    closure_threshold: int | None = None,
    depth_key: int | None = None,
) -> gpd.GeoDataFrame:
    """Merge exposure + dual fragility into legacy-compatible road_links output."""
    threshold = int(
        closure_threshold
        if closure_threshold is not None
        else depth_key
        if depth_key is not None
        else scenario_param
    )
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

    links = apply_max_speed_to_links(links, depth_key=threshold)
    return apply_legacy_flood_columns(
        links,
        depth_key=threshold,
        scenario_param=int(scenario_param),
        event_id=hazard_event.event_id,
    )


def build_snow_link_disruption(
    road_links: gpd.GeoDataFrame,
    intersections: gpd.GeoDataFrame,
    base_scenario_links: gpd.GeoDataFrame,
    *,
    hazard_event: HazardEvent,
    scenario_param: int,
    closure_threshold: int | None = None,
    snow_key_mm: int | None = None,
) -> gpd.GeoDataFrame:
    """Merge snow exposure + dual fragility into legacy-compatible road_links output."""
    threshold = int(
        closure_threshold
        if closure_threshold is not None
        else snow_key_mm
        if snow_key_mm is not None
        else scenario_param
    )
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

    links = apply_snow_max_speed(links, snow_key_mm=threshold)
    return apply_legacy_snow_columns(
        links,
        snow_key_mm=threshold,
        scenario_param=int(scenario_param),
        event_id=hazard_event.event_id,
    )


def build_earthquake_link_disruption(
    road_links: gpd.GeoDataFrame,
    intersections: gpd.GeoDataFrame,
    base_scenario_links: gpd.GeoDataFrame,
    *,
    hazard_event: HazardEvent,
    scenario_param: int,
    scenario_key: int | None = None,
) -> gpd.GeoDataFrame:
    path_key = int(scenario_key if scenario_key is not None else scenario_param)
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
        scenario_param=path_key,
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
    scenario_param: int,
    scenario_key: int | None = None,
) -> gpd.GeoDataFrame:
    path_key = int(scenario_key if scenario_key is not None else scenario_param)
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
        scenario_param=path_key,
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
    scenario_param: int,
    closure_threshold: int | None = None,
    scenario_key: int | None = None,
) -> gpd.GeoDataFrame:
    from resiflow.disruption.winter_storm import features_with_winter_storm
    from resiflow.fragility.winter_storm_operational import apply_max_speed_to_links as apply_ws_max_speed

    path_key = int(scenario_key if scenario_key is not None else scenario_param)
    ice_threshold = int(closure_threshold if closure_threshold is not None else path_key)
    links = features_with_winter_storm(road_links, intersections)
    cols_to_drop = [c for c in _ASSIGNMENT_STATE_COLS if c in links.columns]
    if cols_to_drop:
        links = links.drop(columns=cols_to_drop)
    merge_cols = [c for c in _BASE_SCENARIO_ASSIGNMENT_COLS if c in base_scenario_links.columns]
    links = links.merge(base_scenario_links[merge_cols], how="left", on="e_id")
    links = links.loc[:, ~links.columns.duplicated()]
    links["free_flow_speeds"] = links["free_flow_speeds"].fillna(50.0)
    links = apply_ws_max_speed(links, ice_key_mm=ice_threshold)
    out = apply_legacy_intensity_columns(
        links,
        hazard_type="winter_storm",
        intensity_unit="mm_ice",
        intensity_col="winter_storm_max_mm",
        scenario_param=path_key,
        event_id=hazard_event.event_id,
    )
    out["flood_depth_max"] = out["winter_storm_max_mm"] / 1000.0
    return out


def run_disruption(
    scenario_param: int,
    event_key: str,
    *,
    scenario: HazardScenario | None = None,
    base_path=None,
    hazard_type: str | None = None,
    hazard_source=None,
) -> None:
    """Hazard-agnostic entry point; dispatches flood or snow pipelines."""
    import os
    from pathlib import Path

    from resiflow.hazards.scenario_registry import resolve_active_scenario

    if scenario is None:
        scenario = resolve_active_scenario(
            scenario_param=int(scenario_param),
            event_id=str(event_key),
            base_path=Path(base_path) if base_path is not None else None,
        )

    resolved_type = (
        hazard_type or scenario.hazard_type or os.environ.get("RESIFLOW_HAZARD_TYPE", "flood")
    ).strip().lower()
    path_key = int(scenario.scenario_param)
    threshold = scenario.operational_threshold

    if resolved_type == "snow":
        from resiflow.disruption.pipeline_snow import run_snow_disruption

        run_snow_disruption(
            path_key,
            event_key,
            closure_threshold=threshold,
            base_path=base_path,
            hazard_source=hazard_source,
        )
        return

    if resolved_type == "earthquake":
        from resiflow.disruption.earthquake import intersections_with_earthquake
        from resiflow.disruption.pipeline_intensity import run_intensity_disruption
        from resiflow.hazards.real_va import resolve_real_source
        from resiflow.hazards.sioux_falls_multihazard import EarthquakeHazardSource

        if base_path is None:
            from resiflow.utils import load_config

            base_path = Path(load_config()["paths"]["soge_clusters"])
        if hazard_source is None:
            hazard_source = resolve_real_source(base_path, "earthquake") or EarthquakeHazardSource(
                base_path
            )
        run_intensity_disruption(
            path_key,
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
        from resiflow.hazards.real_va import resolve_real_source
        from resiflow.hazards.sioux_falls_multihazard import LandslideHazardSource

        if base_path is None:
            from resiflow.utils import load_config

            base_path = Path(load_config()["paths"]["soge_clusters"])
        if hazard_source is None:
            hazard_source = resolve_real_source(base_path, "landslide") or LandslideHazardSource(
                base_path
            )
        run_intensity_disruption(
            path_key,
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
        from resiflow.hazards.real_va import resolve_real_source

        if base_path is None:
            from resiflow.utils import load_config

            base_path = Path(load_config()["paths"]["soge_clusters"])
        if hazard_source is None:
            hazard_source = resolve_real_source(base_path, "winter_storm")
        run_winter_storm_disruption(
            path_key,
            event_key,
            closure_threshold=threshold,
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
        import os as _os

        from resiflow.hazards.real_va import resolve_real_source

        flood_subtype = _os.environ.get("RESIFLOW_FLOOD_SUBTYPE", "flood_surface")
        hazard_source = resolve_real_source(base_path, "flood", flood_subtype=flood_subtype)

    if hazard_source is None:
        from resiflow.hazards.sioux_falls_multihazard import resolve_multihazard_flood_source

        mh = resolve_multihazard_flood_source(base_path)
        if mh is not None:
            hazard_source = mh

    run_flood_disruption(
        path_key,
        event_key,
        closure_threshold=threshold,
        base_path=base_path,
        hazard_source=hazard_source,
    )
