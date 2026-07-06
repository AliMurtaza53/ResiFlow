"""Build LinkDisruptionRecord rows from hazard + fragility outputs."""

from __future__ import annotations

import geopandas as gpd
import pandas as pd

from resiflow.disruption.flood import (
    DAMAGE_LEVEL_DICT,
    DAMAGE_LEVEL_DICT_REVERSE,
    features_with_damage,
)
from resiflow.disruption.link_record import apply_legacy_flood_columns, apply_legacy_snow_columns
from resiflow.fragility.flood_operational import apply_max_speed_to_links
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

    from resiflow.disruption.pipeline import run_flood_disruption

    run_flood_disruption(
        scenario_key,
        event_key,
        base_path=base_path,
        hazard_source=hazard_source,
    )
