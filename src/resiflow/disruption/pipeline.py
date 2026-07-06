"""Flood disruption pipeline orchestration (Script 2 logic)."""

from __future__ import annotations

import logging
import time
from pathlib import Path

import geopandas as gpd
import pandas as pd

from resiflow.disruption.build import build_flood_link_disruption
from resiflow.disruption.flood import intersections_with_damage
from resiflow.disruption.io import first_existing, log_summary, validate_output
from resiflow.exposure.raster_line import load_analysis_boundary
from resiflow.hazards.flood import FloodHazardSource
from resiflow.utils import get_results_variant, load_config

def run_flood_disruption(depth_key, event_key, *, base_path=None, hazard_source=None):

    if base_path is None:
        base_path = Path(load_config()["paths"]["soge_clusters"])
    base_path = Path(base_path)
    if hazard_source is None:
        hazard_source = FloodHazardSource(base_path)

    """
    Run flood disruption analysis on road networks under flood scenarios.

    Parameters:
        depth_key (int): Flood depth threshold in centimeters for road closure.
                        Determines when roads become impassable. Common values: 15, 30, 60 cm.
                        Controls the speed reduction curve for flooded roads.
        event_key (str): Scenario identifier for flood event.
                For the Fairfax toy dataset use:
                - '1' = base
                - '2' = low
                - '3' = high
                Used to locate hazard rasters and organize outputs.

    Model Inputs:
        - edge_flows_32p.gpq:
            Base scenario output containing road network simulation results.
        - faf5_road_links.gpq:
            GeoDataFrame of road network elements with attributes.
        - JBA Flood Map (RASTER):
            Raster data representing flood scenarios.
        - JBA Flood Map (Vector):
            Vector data used for clipping road links to flood extents.

    Model Outputs:
        - intersections_x.pq:
            GeoDataFrame of feature intersections with flood depth and damage levels.
        - road_links_x.gpq:
            GeoDataFrame of road links with aggregated maximum flood depth and
                damage levels.

    Returns:
        None: Outputs are saved to files.
    """
    # Normalize event key so calls from CLI and direct Python are consistent
    event_key = str(event_key).strip()
    logging.info(f"[MAIN START] depth_key={depth_key} cm, event_key={event_key}")

    # base scenario simulation results
    base_scenario_path = (
        base_path.parent
        / "results"
        / "base_scenario"
        / get_results_variant()
        / "edge_flows.gpq"
    )
    logging.info(f"[LOAD] Loading base scenario from {base_scenario_path}")
    print(f"DEBUG: Loading {base_scenario_path} (exists={base_scenario_path.exists()})")
    base_scenario_links = gpd.read_parquet(base_scenario_path)
    logging.info(f"[LOAD] Base scenario loaded: {len(base_scenario_links)} rows")
    print(f"DEBUG: Base scenario shape={base_scenario_links.shape}")
    
    # Remove duplicate columns if they exist
    base_scenario_links = base_scenario_links.loc[:, ~base_scenario_links.columns.duplicated()]

    # If both acc_* and current_* exist, prefer current_* and drop acc_*
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
    base_scenario_links = base_scenario_links.loc[:, ~base_scenario_links.columns.duplicated()]

    # load analysis boundary (DMV study area preferred)
    analysis_boundary = load_analysis_boundary(base_path)

    road_links_path = first_existing(
        [
            base_path / "networks" / "faf5" / "faf5_road_links.gpq",
            base_path / "inputs" / "networks" / "faf5" / "faf5_road_links.gpq",
        ]
    )
    if road_links_path is None:
        raise FileNotFoundError(
            "Could not find faf5_road_links.gpq in standard or toy input paths"
        )

    if hazard_source.is_toy_mode and hazard_source._toy_clip_path is None:
        logging.warning(
            "No toy study-area clip file found; falling back to analysis boundary clipping only."
        )

    event_dict = hazard_source.build_event_file_map(event_key)

    # analysis
    logging.info(f"[ANALYSIS] Found {len(event_dict)} flood events, filtering for event_key={event_key}")
    print(f"DEBUG: event_dict keys={list(event_dict.keys())}")
    
    processed_event = False
    for flood_key, v in event_dict.items():
        if not hazard_source.is_toy_mode and flood_key != event_key:
            logging.info(f"[SKIP] Skipping flood_key={flood_key} (not matching event_key={event_key})")
            continue
        processed_event = True
        hazard_event = hazard_source.resolve_event(flood_key)
        logging.info(f"[PROCESS] Starting intersection analysis for flood_key={flood_key}")
        print(f"DEBUG: Starting intersection for event {flood_key}...")
        # out path
        out_path = (
            base_path.parent
            / "results"
            / "disruption_analysis"
            / get_results_variant()
            / str(depth_key)
        )
        logging.info(f"[PATHS] Output directory: {out_path}")
        print(f"DEBUG: Output path={out_path}")
        
        # Load road links once outside the loop for efficiency
        # load road links (SUBNETWORK)
        road_links = gpd.read_parquet(road_links_path)
        logging.info(f"[LOAD] Road links loaded for event {flood_key}: {len(road_links)} rows")

        intersections = gpd.GeoDataFrame(
            columns=["e_id", "length", "index_i", "index_j"]
        )

        for flood_type, flood_paths in v.items():
            logging.info(f"[FLOOD_TYPE] Processing flood_type={flood_type} with {len(flood_paths)} files")
            print(f"DEBUG: Processing {flood_type} with {len(flood_paths)} rasters")
            # Use a fresh copy for each flood type to avoid accumulated columns
            road_links_fresh = road_links.copy()
            
            for flood_path in flood_paths:
                logging.info(f"[RASTER] Processing raster: {flood_path}")
                print(f"DEBUG: Processing raster {Path(flood_path).name}")
                
                if hazard_source.is_toy_mode:
                    clip_path = hazard_source._toy_clip_path
                else:
                    clip_path = hazard_source.clip_path_for_raster(flood_path, hazard_event)
                    if clip_path is None:
                        logging.info(f"[SKIP] Cannot find vector file for: {flood_path}")
                        print("DEBUG: Missing vector clip file")
                        continue

                # intersections
                logging.info(f"[INTERSECT] Computing intersections for {flood_type}...")
                raster_start = time.perf_counter()
                temp_file = intersections_with_damage(
                    road_links_fresh,
                    flood_key,
                    flood_type,
                    flood_path,
                    clip_path,
                    analysis_boundary,
                )
                if temp_file is None:
                    logging.warning(f"[INTERSECT_FAIL] No results from intersections_with_damage")
                    continue
                raster_elapsed = time.perf_counter() - raster_start
                logging.info(
                    f"[INTERSECT_OK] Got {len(temp_file)} intersection results in {raster_elapsed:.2f}s"
                )
                merge_columns = [
                    "e_id",
                    "length",
                    "index_i",
                    "index_j",
                    f"flood_depth_{flood_type}",
                    f"damage_level_{flood_type}",
                ]
                if flood_type == "flood":
                    # Preserve compatibility mirror columns for Script 3/4.
                    merge_columns.extend(["flood_depth_river", "damage_level_river"])
                intersections = intersections.merge(
                    temp_file[merge_columns],
                    on=["e_id", "length", "index_i", "index_j"],
                    how="outer",
                )

        # save intersectiosn for damage analysis
        if intersections.empty:
            logging.warning("[EMPTY] Intersections result is empty! Skipping output.")
            print("DEBUG: Intersections are empty!")
            continue

        logging.info(f"[SAVE_INTERSECT] Saving {len(intersections)} intersection rows")
        (out_path / "intersections").mkdir(parents=True, exist_ok=True)
        intersections_path = out_path / "intersections" / f"intersections_{flood_key}.pq"
        intersections.to_parquet(intersections_path)
        validate_output(intersections_path, intersections, "intersections")
        log_summary("intersections", intersections)
        print(f"DEBUG: Saved intersections to {intersections_path}")

        # road integrations - reload fresh copy
        logging.info(f"[FEATURES] Computing features_with_damage...")
        road_links = build_flood_link_disruption(
            road_links,
            intersections,
            base_scenario_links,
            hazard_event=hazard_event,
            depth_key=depth_key,
        )
        logging.info(f"[FEATURES_OK] Features computed, {len(road_links)} road links")

        (out_path / "links").mkdir(parents=True, exist_ok=True)
        links_path = out_path / "links" / f"road_links_{flood_key}.gpq"
        logging.info(f"[SAVE_LINKS] Saving {len(road_links)} road links to {links_path}")
        road_links.to_parquet(links_path)
        validate_output(links_path, road_links, "road_links")
        log_summary("road_links", road_links)
        logging.info(f"[COMPLETE] Script 2 completed successfully for event_key={event_key}, depth_key={depth_key}")
        print(f"DEBUG: Script 2 COMPLETE! Outputs saved to {out_path}")

    if not processed_event:
        logging.warning(
            f"[NO_MATCH] event_key={event_key} not found in discovered events: {list(event_dict.keys())}"
        )
        print(f"DEBUG: No matching event_key={event_key}. Available events: {list(event_dict.keys())}")
