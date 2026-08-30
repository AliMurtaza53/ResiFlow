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
    # NOT a cost shim anymore (comment corrected 2026-08-29 -- the prior
    # version of this comment, dated 2026-08-20, described a real gap that
    # a6b6f0b then fixed and is now stale/misleading). Direct damage cost for
    # earthquake is priced by scripts/3_damage_analysis.py's hazard_type
    # branch, which routes to hazards/hazus_bridge.py's
    # compute_row_direct_damage_musd() (real FEMA HAZUS 6.1 Ch.7 bridge
    # fragility/cost, Sa(1.0s)-based) -- calculate_damage()'s flood-curve
    # path is only reached for hazard_type == "flood" now.
    #
    # flood_depth_max is still set here (PGA(g) * 0.5, an arbitrary
    # unit-matching multiplier, not a real depth-equivalent conversion) and
    # is still LIVE, not vestigial: Script 4's residual-floodwater speed
    # gates (day-2/day-3 recovery, "apply speed constraint to roads with
    # flooddepth (2-6) metres") key off this same column for every hazard
    # type, earthquake included. Whether a residual-floodwater-style speed
    # constraint should apply to earthquake-damaged roads at all -- there's
    # no floodwater to recede -- is an open methodological question, not
    # resolved by this comment; flagging so it isn't mistaken for dead code.
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
    # NOT a cost shim anymore (see build_earthquake_link_disruption's comment
    # above -- same correction applies). Landslide direct damage is also
    # priced via hazards/hazus_bridge.py's compute_row_direct_damage_musd()
    # (hazard_type == "landslide" branch, HAZUS's ground-failure/PGD
    # fragility for both bridges and ordinary roads -- a defensible proxy
    # since PGD is genuinely the shared mechanism, not a landslide-bespoke
    # curve, since HAZUS has no separate landslide module).
    #
    # flood_depth_max (PGD mm / 1000, an arbitrary unit-matching conversion)
    # is still LIVE, not vestigial -- see the same note in
    # build_earthquake_link_disruption re: Script 4's residual-floodwater
    # speed gates keying off this column for every hazard type.
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
    # SHIM, NOT A REAL COST MODEL -- unlike earthquake/landslide (see
    # build_earthquake_link_disruption's comment above), this one is still
    # accurate: scripts/3_damage_analysis.py's hazard_type branch only
    # special-cases earthquake/landslide, so winter_storm still falls through
    # to calculate_damage()'s flood-curve path -- ice/snow mm / 1000
    # repackaged as a fake "flood depth" in metres, then priced with FLOOD's
    # damage_ratio/cost tables. No HAZUS reference exists for this hazard
    # (winter storm isn't one of HAZUS's four modules) -- a real cost table
    # here would need a different source, e.g. state DOT snow/ice removal
    # cost data. Confirmed independently wrong by ~150-1000x against
    # real-world Winter Storm Jonas damage estimates (see
    # results/finale_2026_08/build_finale_figures.py's WINTER_STORM_EXCLUSION).
    #
    # flood_depth_max is also read by Script 4's residual-floodwater speed
    # gates (day-2/day-3 recovery) -- unlike earthquake/landslide, a
    # residual-snow-on-the-road-receding-over-days analogy is at least
    # plausible for this hazard, though the gate thresholds (2m/6m) were
    # tuned for actual floodwater, not snow depth, and haven't been
    # re-validated for this use.
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
        from resiflow.hazards.real_events import resolve_real_source
        from resiflow.hazards.sioux_falls_multihazard import EarthquakeHazardSource

        if base_path is None:
            from resiflow.utils import load_config

            base_path = Path(load_config()["paths"]["soge_clusters"])
        if hazard_source is None:
            earthquake_subtype = (
                scenario.hazard_subtype
                or os.environ.get("RESIFLOW_EARTHQUAKE_SUBTYPE", "").strip()
                or None
            )
            hazard_source = resolve_real_source(
                base_path, "earthquake", hazard_subtype=earthquake_subtype
            ) or EarthquakeHazardSource(base_path)
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
        from resiflow.hazards.real_events import resolve_real_source
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
        from resiflow.hazards.real_events import resolve_real_source

        if base_path is None:
            from resiflow.utils import load_config

            base_path = Path(load_config()["paths"]["soge_clusters"])
        if hazard_source is None:
            # BUG (found 2026-08-21): this branch never read scenario.hazard_subtype,
            # unlike earthquake's/landslide's branches -- resolve_real_source(...,
            # "winter_storm") with no hazard_subtype always mapped to the "winter_storm"
            # key (RealWinterStormSource, the original 2016 Jonas raster), REGARDLESS of
            # scenario_param. Confirmed on Hopper: scenario_param 601/602/603/604 (Jonas/
            # Uri/Elliott/Snowmageddon, distinct hazard_subtypes in scenario_registry.py)
            # all produced IDENTICAL direct_damage_total/rerouting_cost, because all four
            # silently ran against the same Jonas raster under different labels -- not a
            # coincidence, this was the mechanism. Fixed to read scenario.hazard_subtype
            # first, same pattern as the earthquake branch above.
            winter_storm_subtype = (
                scenario.hazard_subtype
                or os.environ.get("RESIFLOW_WINTER_STORM_SUBTYPE", "").strip()
                or None
            )
            hazard_source = resolve_real_source(
                base_path, "winter_storm", hazard_subtype=winter_storm_subtype
            )
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

        from resiflow.hazards.real_events import resolve_real_source

        flood_subtype = (
            scenario.hazard_subtype
            or _os.environ.get("RESIFLOW_FLOOD_SUBTYPE", "").strip()
            or "flood_surface"
        )
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
