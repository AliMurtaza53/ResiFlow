"""Flood disruption: exposure + fragility aggregation onto links."""

from __future__ import annotations

import logging
import sys
from typing import Dict, Optional

import geopandas as gpd
import numpy as np
import pandas as pd

from resiflow.exposure.raster_line import (
    clip_features,
    intersect_features_with_raster,
    subset_features_to_raster_extent,
)
from resiflow.fragility.flood_categorical import compute_damage_levels_on_flooded_roads_vectorized

DAMAGE_LEVEL_DICT: Dict[str, int] = {
    "no": 0,
    "minor": 1,
    "moderate": 2,
    "extensive": 3,
    "severe": 4,
}
DAMAGE_LEVEL_DICT_REVERSE: Dict[int, str] = {v: k for k, v in DAMAGE_LEVEL_DICT.items()}


def intersections_with_damage(
    road_links: gpd.GeoDataFrame,
    flood_key: str,
    flood_type: str,
    flood_path: str,
    clip_path: Optional[str],
    boundary_gdf: Optional[gpd.GeoDataFrame] = None,
) -> gpd.GeoDataFrame:
    """
    Computes flood depth and damage levels for road segments by intersecting them with
        flood data.

    Parameters:
        road_links (gpd.GeoDataFrame): GeoDataFrame of road links with geometries and
            classifications.
        flood_key (str): Identifier for the flood dataset.
        flood_type (str): Type of flood ("surface" or "river").
        flood_path (str): Path to the flood raster file.
        clip_path (str): Path to the vector file used for clipping.

    Returns:
        gpd.GeoDataFrame: GeoDataFrame of intersections with calculated flood depths
            and damage levels.
    """

    # First restrict to the raster footprint so national-scale networks do not
    # enter the expensive line-splitting/intersection path for a local hazard.
    candidate_links = subset_features_to_raster_extent(road_links, flood_path)

    # Clip road links with features in the provided vector file/boundary.
    clipped_features = clip_features(candidate_links, clip_path, flood_key, boundary_gdf)
    if clipped_features.empty:
        logging.info("Warning: Clip features is None!")
        return None
    # Perform intersection analysis with the flood raster
    intersections = intersect_features_with_raster(
        flood_path,
        flood_key,
        clipped_features,
        flood_type,
    )
    intersections.reset_index(drop=True, inplace=True)
    # Adjust flood depths for embankment heights based on road classification
    """
    embankment against surface flood: 100 cm (motorways/major roads)
    embankment against river flood: 200 cm (motorways/major roads)
    """
    # Determine major roads for embankment adjustment (works for both UK and FAF classifications)
    is_major_road = intersections["road_classification"].astype(str).str.lower().isin(
        ["motorway", "motorway_link", "trunk", "primary", "secondary"]
    )
    
    if flood_type == "surface":
        intersections.loc[is_major_road, "flood_depth_surface"] = (
            intersections.loc[is_major_road, "flood_depth_surface"] - 100
        ).clip(lower=0)
    else:
        flood_depth_col = f"flood_depth_{flood_type}"
        intersections.loc[is_major_road, flood_depth_col] = (
            intersections.loc[is_major_road, flood_depth_col] - 200
        ).clip(lower=0)

    # Compute damage levels for flooded road segments
    intersections[f"damage_level_{flood_type}"] = compute_damage_levels_on_flooded_roads_vectorized(
        flood_type,
        intersections["road_classification"],
        intersections["trunk_road"] if "trunk_road" in intersections.columns else pd.Series(False, index=intersections.index),
        intersections["road_label"] if "road_label" in intersections.columns else pd.Series("", index=intersections.index),
        intersections[f"flood_depth_{flood_type}"],
    )
    if flood_type == "coastal":
        intersections["flood_depth_surface"] = intersections["flood_depth_coastal"]
        intersections["damage_level_surface"] = intersections["damage_level_coastal"]
        intersections["flood_depth_river"] = 0.0
        intersections["damage_level_river"] = "no"
    if flood_type == "flood":
        # Keep a clear generic flood label in Script 2 outputs while mirroring to
        # river_* for Script 3/4, which still consume the historical schema.
        intersections["flood_depth_river"] = intersections["flood_depth_flood"]
        intersections["damage_level_river"] = intersections["damage_level_flood"]

    return intersections


def features_with_damage(
    features: gpd.GeoDataFrame,
    intersections: gpd.GeoDataFrame,
    damage_level_dict: Dict,
    damage_level_dict_reverse: Dict,
) -> gpd.GeoDataFrame:
    """
    Aggregates flood depth and damage levels for road links based on intersection data.

    Parameters:
        features (gpd.GeoDataFrame): GeoDataFrame of road links.
        intersections (gpd.GeoDataFrame): GeoDataFrame of intersections with flood data.
        damage_level_dict (Dict): Mapping of damage levels to numerical values.
        damage_level_dict_reverse (Dict): Reverse mapping of numerical values to damage
            levels.

    Returns:
        gpd.GeoDataFrame: Updated GeoDataFrame of road links with maximum flood depth
            and damage levels.
    """

    # Flood depth
    if (
        "flood_depth_surface" in intersections.columns
        and "flood_depth_river" in intersections.columns
    ):
        intersections["flood_depth_max"] = intersections[
            ["flood_depth_surface", "flood_depth_river"]
        ].max(axis=1)
    elif "flood_depth_surface" in intersections.columns:
        intersections["flood_depth_max"] = intersections.flood_depth_surface
    elif "flood_depth_flood" in intersections.columns:
        intersections["flood_depth_max"] = intersections.flood_depth_flood
    elif "flood_depth_river" in intersections.columns:
        intersections["flood_depth_max"] = intersections.flood_depth_river
    elif "flood_depth_coastal" in intersections.columns:
        intersections["flood_depth_max"] = intersections.flood_depth_coastal
    else:
        logging.info("Error: flood depth columns are missing!")
        sys.exit()

    # Damage level
    if (
        "damage_level_surface" in intersections.columns
        and "damage_level_river" in intersections.columns
    ):
        intersections["damage_level_surface"] = intersections[
            "damage_level_surface"
        ].map(damage_level_dict)
        intersections["damage_level_river"] = intersections["damage_level_river"].map(
            damage_level_dict
        )
        intersections["damage_level_max"] = intersections[
            ["damage_level_surface", "damage_level_river"]
        ].max(axis=1)
    elif "damage_level_surface" in intersections.columns:
        intersections["damage_level_surface"] = intersections[
            "damage_level_surface"
        ].map(damage_level_dict)
        intersections["damage_level_max"] = intersections.damage_level_surface
    elif "damage_level_flood" in intersections.columns:
        intersections["damage_level_flood"] = intersections[
            "damage_level_flood"
        ].map(damage_level_dict)
        intersections["damage_level_max"] = intersections.damage_level_flood
    elif "damage_level_river" in intersections.columns:
        intersections["damage_level_river"] = intersections["damage_level_river"].map(
            damage_level_dict
        )
        intersections["damage_level_max"] = intersections.damage_level_river
    elif "damage_level_coastal" in intersections.columns:
        intersections["damage_level_coastal"] = intersections["damage_level_coastal"].map(
            damage_level_dict
        )
        intersections["damage_level_max"] = intersections.damage_level_coastal
    else:
        logging.info("Error: damage level columns are missing!")
        intersections["damage_level_max"] = damage_level_dict["no"]

    intersections_gp = intersections.groupby("e_id", as_index=False).agg(
        {
            "flood_depth_max": "max",
            "damage_level_max": "max",
        }
    )
    intersections_gp["damage_level_max"] = (
        pd.to_numeric(intersections_gp["damage_level_max"], errors="coerce")
        .replace([np.inf, -np.inf], np.nan)
        .fillna(0)
        .astype(int)
        .map(damage_level_dict_reverse)
    )

    features = features.merge(
        intersections_gp[["e_id", "flood_depth_max", "damage_level_max"]],
        how="left",
        on="e_id",
    )
    features["flood_depth_max"] = features["flood_depth_max"].fillna(0.0)
    features["damage_level_max"] = features["damage_level_max"].fillna("no")

    return features