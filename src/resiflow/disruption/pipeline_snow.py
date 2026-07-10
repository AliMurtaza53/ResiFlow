"""Snow disruption pipeline orchestration (Script 2 snow path)."""

from __future__ import annotations

import logging
import time
from pathlib import Path

import geopandas as gpd

from resiflow.disruption.build import build_snow_link_disruption
from resiflow.disruption.io import first_existing, log_summary, validate_output
from resiflow.disruption.snow import intersections_with_snow
from resiflow.exposure.raster_line import load_analysis_boundary
from resiflow.hazards.snow import SnowHazardSource
from resiflow.utils import get_results_variant, load_config


def _load_base_scenario_links(base_path: Path) -> gpd.GeoDataFrame:
    base_scenario_path = (
        base_path.parent
        / "results"
        / "base_scenario"
        / get_results_variant()
        / "edge_flows.gpq"
    )
    base_scenario_links = gpd.read_parquet(base_scenario_path)
    base_scenario_links = base_scenario_links.loc[:, ~base_scenario_links.columns.duplicated()]
    for acc_col, cur_col in (
        ("acc_capacity", "current_capacity"),
        ("acc_speed", "current_speed"),
        ("acc_flow", "current_flow"),
    ):
        if acc_col in base_scenario_links.columns and cur_col in base_scenario_links.columns:
            base_scenario_links = base_scenario_links.drop(columns=[acc_col])
    base_scenario_links.rename(
        columns={
            "acc_capacity": "current_capacity",
            "acc_speed": "current_speed",
            "acc_flow": "current_flow",
        },
        inplace=True,
    )
    return base_scenario_links.loc[:, ~base_scenario_links.columns.duplicated()]


def run_snow_disruption(
    scenario_param,
    event_key,
    *,
    closure_threshold: int | None = None,
    base_path=None,
    hazard_source=None,
) -> None:
    """Run snow disruption analysis; outputs use legacy Script 3/4 paths."""
    if base_path is None:
        base_path = Path(load_config()["paths"]["soge_clusters"])
    base_path = Path(base_path)
    if hazard_source is None:
        hazard_source = SnowHazardSource(base_path)

    event_key = str(event_key).strip()
    snow_key_mm = int(closure_threshold if closure_threshold is not None else scenario_param)
    path_key = int(scenario_param)
    logging.info(
        "[SNOW START] scenario_param=%s closure_threshold=%s mm, event_key=%s",
        path_key,
        snow_key_mm,
        event_key,
    )

    base_scenario_links = _load_base_scenario_links(base_path)
    analysis_boundary = load_analysis_boundary(base_path)
    road_links_path = first_existing(
        [
            base_path / "networks" / "faf5" / "faf5_road_links.gpq",
            base_path / "inputs" / "networks" / "faf5" / "faf5_road_links.gpq",
        ]
    )
    if road_links_path is None:
        raise FileNotFoundError("Could not find faf5_road_links.gpq")

    event_dict = hazard_source.build_event_file_map(event_key)
    processed_event = False

    for snow_event_id, field_map in event_dict.items():
        if not hazard_source.is_toy_mode and snow_event_id != event_key:
            continue
        processed_event = True
        hazard_event = hazard_source.resolve_event(snow_event_id)
        out_path = (
            base_path.parent
            / "results"
            / "disruption_analysis"
            / get_results_variant()
            / str(path_key)
        )
        road_links = gpd.read_parquet(road_links_path)
        intersections = gpd.GeoDataFrame(columns=["e_id", "length", "index_i", "index_j"])

        for field_name, raster_paths in field_map.items():
            for raster_path in raster_paths:
                clip_path = hazard_source.clip_path_for_raster(hazard_event)
                clip_str = str(clip_path) if clip_path is not None else None
                raster_start = time.perf_counter()
                temp_file = intersections_with_snow(
                    road_links,
                    snow_event_id,
                    raster_path,
                    clip_str,
                    analysis_boundary,
                )
                if temp_file is None or temp_file.empty:
                    continue
                raster_elapsed = time.perf_counter() - raster_start
                logging.info(
                    "[SNOW INTERSECT] field=%s rows=%s in %.2fs",
                    field_name,
                    len(temp_file),
                    raster_elapsed,
                )
                merge_columns = [
                    "e_id",
                    "length",
                    "index_i",
                    "index_j",
                    "snow_depth_mm",
                    "damage_level_snow",
                    "flood_depth_surface",
                    "flood_depth_river",
                    "damage_level_surface",
                    "damage_level_river",
                ]
                intersections = intersections.merge(
                    temp_file[merge_columns],
                    on=["e_id", "length", "index_i", "index_j"],
                    how="outer",
                )

        if intersections.empty:
            logging.warning("[SNOW EMPTY] No intersections for event %s", snow_event_id)
            continue

        (out_path / "intersections").mkdir(parents=True, exist_ok=True)
        intersections_path = out_path / "intersections" / f"intersections_{snow_event_id}.pq"
        intersections.to_parquet(intersections_path)
        validate_output(intersections_path, intersections, "intersections")

        road_links = build_snow_link_disruption(
            road_links,
            intersections,
            base_scenario_links,
            hazard_event=hazard_event,
            scenario_param=path_key,
            closure_threshold=snow_key_mm,
        )
        (out_path / "links").mkdir(parents=True, exist_ok=True)
        links_path = out_path / "links" / f"road_links_{snow_event_id}.gpq"
        road_links.to_parquet(links_path)
        validate_output(links_path, road_links, "road_links")
        log_summary("road_links", road_links)
        logging.info(
            "[SNOW COMPLETE] event_key=%s scenario_param=%s closure_threshold=%s",
            event_key,
            path_key,
            snow_key_mm,
        )

    if not processed_event:
        logging.warning(
            "[SNOW NO_MATCH] event_key=%s not in discovered events: %s",
            event_key,
            list(event_dict.keys()),
        )
