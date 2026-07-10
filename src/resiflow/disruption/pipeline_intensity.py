"""Generic intensity-hazard disruption pipeline (earthquake, landslide, winter storm)."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Callable

import geopandas as gpd

from resiflow.disruption.io import first_existing, log_summary, validate_output
from resiflow.exposure.raster_line import load_analysis_boundary
from resiflow.hazards.base import HazardEvent
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


def run_intensity_disruption(
    scenario_key: int,
    event_key: str,
    *,
    hazard_label: str,
    hazard_source,
    intersections_fn: Callable,
    build_link_fn: Callable,
    base_path: Path | None = None,
) -> None:
    """Run intensity raster disruption for multihazard testbed sources."""
    if base_path is None:
        base_path = Path(load_config()["paths"]["soge_clusters"])
    base_path = Path(base_path)
    event_key = str(event_key).strip()
    logging.info("[%s START] scenario_key=%s event_key=%s", hazard_label.upper(), scenario_key, event_key)

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
    raster_field = getattr(hazard_source, "raster_field", hazard_label)

    for hazard_event_id, field_map in event_dict.items():
        processed_event = True
        hazard_event: HazardEvent = hazard_source.resolve_event(hazard_event_id)
        out_path = (
            base_path.parent
            / "results"
            / "disruption_analysis"
            / get_results_variant()
            / str(scenario_key)
        )
        road_links = gpd.read_parquet(road_links_path)
        intersections = gpd.GeoDataFrame(columns=["e_id", "length", "index_i", "index_j"])

        for _field_name, raster_paths in field_map.items():
            for raster_path in raster_paths:
                clip_path = hazard_source.clip_path_for_raster(hazard_event)
                clip_str = str(clip_path) if clip_path is not None else None
                raster_start = time.perf_counter()
                temp_file = intersections_fn(
                    road_links,
                    hazard_event_id,
                    raster_path,
                    clip_str,
                    analysis_boundary,
                )
                if temp_file is None or temp_file.empty:
                    continue
                logging.info(
                    "[%s INTERSECT] rows=%s in %.2fs",
                    hazard_label.upper(),
                    len(temp_file),
                    time.perf_counter() - raster_start,
                )
                merge_columns = [
                    c
                    for c in temp_file.columns
                    if c
                    in {
                        "e_id",
                        "length",
                        "index_i",
                        "index_j",
                        "flood_depth_surface",
                        "flood_depth_river",
                        "damage_level_surface",
                        "damage_level_river",
                    }
                    or c.startswith("flood_depth_")
                    or c.startswith("damage_level_")
                    or c.endswith("_mm")
                    or c.endswith("_g")
                ]
                intersections = intersections.merge(
                    temp_file[merge_columns],
                    on=["e_id", "length", "index_i", "index_j"],
                    how="outer",
                )

        if intersections.empty:
            logging.warning("[%s EMPTY] No intersections for event %s", hazard_label.upper(), hazard_event_id)
            continue

        (out_path / "intersections").mkdir(parents=True, exist_ok=True)
        intersections_path = out_path / "intersections" / f"intersections_{hazard_event_id}.pq"
        intersections.to_parquet(intersections_path)
        validate_output(intersections_path, intersections, "intersections")

        road_links = build_link_fn(
            road_links,
            intersections,
            base_scenario_links,
            hazard_event=hazard_event,
            scenario_key=int(scenario_key),
        )
        (out_path / "links").mkdir(parents=True, exist_ok=True)
        links_path = out_path / "links" / f"road_links_{hazard_event_id}.gpq"
        road_links.to_parquet(links_path)
        validate_output(links_path, road_links, "road_links")
        log_summary("road_links", road_links)
        logging.info("[%s COMPLETE] event=%s", hazard_label.upper(), hazard_event_id)

    if not processed_event:
        logging.warning("[%s NO_MATCH] event_key=%s", hazard_label.upper(), event_key)
