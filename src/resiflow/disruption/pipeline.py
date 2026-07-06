"""Flood disruption pipeline orchestration (Script 2 logic)."""

from __future__ import annotations

import logging
import os
import re
import time
from collections import defaultdict
from pathlib import Path

import geopandas as gpd
import pandas as pd

from resiflow.disruption.flood import (
    DAMAGE_LEVEL_DICT,
    DAMAGE_LEVEL_DICT_REVERSE,
    features_with_damage,
    intersections_with_damage,
)
from resiflow.disruption.io import first_existing, log_summary, validate_output
from resiflow.disruption.link_record import apply_legacy_flood_columns
from resiflow.exposure.raster_line import load_analysis_boundary
from resiflow.fragility.flood_operational import apply_max_speed_to_links
from resiflow.utils import get_results_variant, load_config

def run_flood_disruption(depth_key, event_key, *, base_path=None):

    if base_path is None:
        base_path = Path(load_config()["paths"]["soge_clusters"])
    raster_path = base_path / "hazards" / "completed"

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
        - GB_road_links_with_bridges.gpq:
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

    damage_level_dict = DAMAGE_LEVEL_DICT
    damage_level_dict_reverse = DAMAGE_LEVEL_DICT_REVERSE

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

    toy_hazard_dir = base_path / "inputs" / "test_17node"
    toy_hazard_50m_dir = base_path / "inputs" / "test_141node_50m"
    toy_hazard_candidates = [
        # Prefer higher-resolution 50 m VA rasters if available
        toy_hazard_50m_dir / "va_hazard_class50_141node_base.tif",
        toy_hazard_50m_dir / "va_hazard_class50_141node_low.tif",
        toy_hazard_50m_dir / "va_hazard_class50_141node_high.tif",
        toy_hazard_50m_dir / "va_hazard_class50_141node.tif",
        # Fall back to 1 km VA rasters
        base_path / "inputs" / "test_141node" / "va_hazard_class50_141node_base.tif",
        base_path / "inputs" / "test_141node" / "va_hazard_class50_141node_low.tif",
        base_path / "inputs" / "test_141node" / "va_hazard_class50_141node_high.tif",
        base_path / "inputs" / "test_141node" / "va_hazard_class50_141node.tif",
        # Fall back to Fairfax test rasters
        toy_hazard_dir / "fairfax_hazard_class50_17node_base.tif",
        toy_hazard_dir / "fairfax_hazard_class50_17node_low.tif",
        toy_hazard_dir / "fairfax_hazard_class50_17node_high.tif",
        toy_hazard_dir / "fairfax_hazard_class50_17node.tif",
    ]
    toy_hazard_path = first_existing(toy_hazard_candidates)

    if toy_hazard_path is not None:
        toy_clip_path = first_existing(
            [
                base_path / "study_area" / "fairfax_study_area.gpkg",
                base_path / "study_area" / "fairfax_study_area.geojson",
                base_path / "study_area" / "va_study_area.gpkg",
                base_path / "study_area" / "va_study_area.geojson",
            ]
        )
        if toy_clip_path is None:
            logging.warning(
                "No toy study-area clip file found; falling back to analysis boundary clipping only."
            )

        toy_variant_map = {1: "base", 2: "low", 3: "high"}
        if event_key.lower() == "all":
            toy_event_keys = sorted(toy_variant_map)
        else:
            try:
                toy_event_keys = [int(part.strip()) for part in event_key.split(",") if part.strip()]
            except (TypeError, ValueError):
                raise ValueError(
                    "In toy mode, event_key must be one of: 1, 2, 3, all, or a comma-separated list like 2,3"
                )
        invalid_event_keys = [key for key in toy_event_keys if key not in toy_variant_map]
        if invalid_event_keys:
            raise ValueError(
                f"Invalid toy-mode event_key(s)={invalid_event_keys}. Use 1=base, 2=low, 3=high, all, or e.g. 2,3."
            )

        # In toy mode these scenario rasters represent the available flood hazard,
        # not a separate surface/river pair. Use the generic "flood" label for
        # clarity; intersections_with_damage mirrors flood_* to river_* for
        # Script 3/4 compatibility. Set NIRD_TOY_FLOOD_TYPES=surface,river only
        # for legacy comparison runs.
        toy_flood_types_raw = os.environ.get("NIRD_TOY_FLOOD_TYPES", "flood")
        toy_flood_types = [
            flood_type.strip().lower()
            for flood_type in toy_flood_types_raw.split(",")
            if flood_type.strip()
        ]
        valid_toy_flood_types = {"surface", "river", "flood"}
        invalid_toy_flood_types = [
            flood_type
            for flood_type in toy_flood_types
            if flood_type not in valid_toy_flood_types
        ]
        if invalid_toy_flood_types:
            raise ValueError(
                "NIRD_TOY_FLOOD_TYPES may only contain 'surface', 'river', and/or 'flood'. "
                f"Got: {invalid_toy_flood_types}"
            )
        if not toy_flood_types:
            raise ValueError("NIRD_TOY_FLOOD_TYPES resolved to no flood types.")
        event_files_by_key = {}
        for event_key_num in toy_event_keys:
            toy_variant = toy_variant_map[event_key_num]
            selected_tif = first_existing(
                [
                    # Prefer 50 m rasters
                    toy_hazard_50m_dir / f"va_hazard_class50_141node_{toy_variant}.tif",
                    # Fall back to 1 km VA rasters
                    base_path / "inputs" / "test_141node" / f"va_hazard_class50_141node_{toy_variant}.tif",
                    # Fall back to Fairfax 17-node rasters
                    toy_hazard_dir / f"fairfax_hazard_class50_17node_{toy_variant}.tif",
                    toy_hazard_path,
                ]
            )
            logging.info(
                f"Toy hazard raster mode enabled: event_key={event_key_num} ({toy_variant}) -> {selected_tif}"
            )
            event_files_by_key[str(event_key_num)] = {
                flood_type: [str(selected_tif)]
                for flood_type in toy_flood_types
            }
        logging.info(f"Toy flood types enabled: {toy_flood_types}")
    else:
        event_files = {flood_type: [] for flood_type in ["surface", "river"]}

    # flood event classification into surface/river flood (non-toy mode only)
    if toy_hazard_path is None:
        flood_types = ["surface", "river", "both"]
        event_files = {flood_type: [] for flood_type in ["surface", "river"]}
        # Iterate through flood types and process files
        for flood_type in flood_types:
            folder_path = raster_path / flood_type
            if folder_path.exists():
                for raster_dir in folder_path.rglob(
                    "Raster"
                ):  # Search for "Raster" directories
                    for tif_file in raster_dir.rglob(
                        "*.tif"
                    ):  # Find .tif files recursively
                        # Filter files with "RD" in the name and exclude those with "IE"
                        if "RD" in tif_file.name and "IE" not in tif_file.name:
                            if flood_type == "both":
                                if "FLSW" in tif_file.name:
                                    target_flood_type = "surface"
                                elif "FLRF" in tif_file.name:
                                    target_flood_type = "river"
                                else:
                                    continue
                            else:
                                target_flood_type = flood_type

                            # Append the file path to the appropriate flood_type list
                            event_files[target_flood_type].append(str(tif_file))

    event_dict = defaultdict(lambda: defaultdict(list))
    if toy_hazard_path is not None:
        for toy_key, toy_event_files in event_files_by_key.items():
            event_dict[toy_key] = defaultdict(list, toy_event_files)
    else:
        for flood_type, list_of_events in event_files.items():
            for event_path in list_of_events:
                # Extract event from path structure
                # Case 1: surface/EventName/Raster/file.tif → parts[-3]="EventName"
                # Case 2: surface/Raster/file.tif → parts[-3]="surface" → extract from filename
                path_parts = Path(event_path).parts
                potential_event_folder = path_parts[-3] if len(path_parts) >= 3 else None
                
                if potential_event_folder not in ["surface", "river", "both", "Raster"]:
                    # It's a meaningful event folder name
                    event = potential_event_folder
                else:
                    # Extract from filename - look for numeric identifiers (year, scenario code, etc.)
                    filename = Path(event_path).stem  # filename without extension
                    import re
                    
                    # Find all numeric sequences in the filename
                    numbers = re.findall(r'\d+', filename)
                    event = None
                    
                    # Use first numeric sequence found (typically scenario/year)
                    if numbers:
                        for num in numbers:
                            # Prefer longer numeric sequences (more likely to be a year or meaningful ID)
                            if len(num) >= 3:  # Changed from hardcoded year check
                                event = num
                                break
                        if not event:
                            event = numbers[0] if numbers else "default"
                    else:
                        # Fallback: use first word-like part of filename
                        event = filename.split("_")[0]
                
                if event:
                    event_dict[event][flood_type].append(event_path)

    # analysis
    logging.info(f"[ANALYSIS] Found {len(event_dict)} flood events, filtering for event_key={event_key}")
    print(f"DEBUG: event_dict keys={list(event_dict.keys())}")
    
    processed_event = False
    for flood_key, v in event_dict.items():
        if toy_hazard_path is None and flood_key != event_key:
            logging.info(f"[SKIP] Skipping flood_key={flood_key} (not matching event_key={event_key})")
            continue
        processed_event = True
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
                
                if toy_hazard_path is not None:
                    clip_path = toy_clip_path
                else:
                    # clip path
                    clip_path = Path(
                        flood_path.replace("Raster", "Vector").replace(".tif", ".shp")
                    )
                    clip_path1 = clip_path.with_name(clip_path.name.replace("_RD_", "_VE_"))
                    clip_path2 = clip_path.with_name(clip_path.name.replace("_RD_", "_PR_"))
                    if clip_path1.exists():
                        clip_path = clip_path1
                    elif clip_path2.exists():
                        clip_path = clip_path2
                    else:
                        logging.info(f"[SKIP] Cannot find vector file for: {flood_path}")
                        print(f"DEBUG: Missing vector clip file")
                        continue  # Skip further processing for this file

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
        road_links = features_with_damage(
            road_links,
            intersections,
            damage_level_dict,
            damage_level_dict_reverse,
        )
        logging.info(f"[FEATURES_OK] Features computed, {len(road_links)} road links")

        # max_speed estimation
        """
        Uncertainties of flood depth threshold for road closure (cm): 15, 30, 60
        """
        # attach capacity and speed info on D-0
        # Drop duplicate columns if they exist (from previous iterations)
        logging.info(f"[SPEED] Computing speed restrictions...")
        cols_to_drop = ["combined_label", "free_flow_speeds", "initial_flow_speeds", 
                        "min_flow_speeds", "current_capacity", "current_speed", "current_flow"]
        cols_to_drop = [c for c in cols_to_drop if c in road_links.columns]
        if cols_to_drop:
            road_links = road_links.drop(columns=cols_to_drop)
        
        road_links = road_links.merge(
            base_scenario_links[
                [
                    "e_id",
                    "combined_label",
                    "free_flow_speeds",
                    "initial_flow_speeds",
                    "min_flow_speeds",
                    "current_capacity",
                    "current_speed",
                    "current_flow",
                ]
            ],
            how="left",
            on="e_id",
        )

        # Ensure no duplicate columns after merge
        road_links = road_links.loc[:, ~road_links.columns.duplicated()]

        # Ensure flood depth and speed columns exist and are numeric
        if "flood_depth_max" not in road_links.columns:
            road_links["flood_depth_max"] = 0.0
        road_links["flood_depth_max"] = road_links["flood_depth_max"].fillna(0.0)
        road_links["free_flow_speeds"] = road_links["free_flow_speeds"].fillna(50.0)

        road_links = apply_max_speed_to_links(road_links, depth_key=depth_key)
        road_links = apply_legacy_flood_columns(
            road_links, depth_key=depth_key, event_id=flood_key
        )
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
