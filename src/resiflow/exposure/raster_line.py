"""Raster-line exposure sampling via snail."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from shapely.geometry import box

from snail import intersection

from resiflow.geo_runtime import (
    CONUS_TARGET_CRS,
    align_extent_to_features_crs,
    build_snail_grid,
    rasterio_env,
)

TARGET_CRS = CONUS_TARGET_CRS

SPLIT_SIMPLIFY_TOLERANCE_M = float(os.environ.get("NIRD_SPLIT_SIMPLIFY_TOLERANCE_M", "0"))
ENABLE_SPLIT_CACHE = os.environ.get("NIRD_ENABLE_SPLIT_CACHE", "0").strip().lower() in {
    "1",
    "true",
    "yes",
}
_SPLIT_CACHE: dict = {}


def first_existing(paths):
    """Return first existing path from a sequence, else None."""
    for path in paths:
        p = Path(path)
        if p.exists():
            return p
    return None


def subset_features_to_raster_extent(
    features: gpd.GeoDataFrame,
    flood_path: str,
    padding_pixels: int = 2,
) -> gpd.GeoDataFrame:
    """Spatially prefilter features to the hazard raster footprint.

    This avoids sending an entire national network into snail's split/intersection
    routine when the hazard raster covers only a small test area.
    """
    if features.empty:
        return features

    with rasterio_env():
        with rasterio.open(flood_path) as dataset:
            bounds = dataset.bounds
            raster_crs = dataset.crs
            pad_x = abs(dataset.transform.a) * padding_pixels
            pad_y = abs(dataset.transform.e) * padding_pixels

    extent_geom = box(
        bounds.left - pad_x,
        bounds.bottom - pad_y,
        bounds.right + pad_x,
        bounds.top + pad_y,
    )

    if raster_crs is None:
        logging.warning(
            "Raster has no CRS; skipping raster-extent feature prefilter for %s",
            flood_path,
        )
        return features

    if features.crs is None:
        logging.warning(
            "Road links have no CRS; skipping raster-extent feature prefilter for %s",
            flood_path,
        )
        return features

    extent = align_extent_to_features_crs(
        extent_geom,
        raster_crs=raster_crs,
        features_crs=features.crs,
        source_name=Path(flood_path).name,
    )

    before = len(features)
    extent_polygon = extent.geometry.iloc[0]
    try:
        candidate_idx = features.sindex.query(extent_polygon, predicate="intersects")
        filtered = features.iloc[np.unique(candidate_idx)].copy()
    except Exception:
        filtered = features[features.intersects(extent_polygon)].copy()

    logging.info(
        "Raster extent prefilter for %s: %s -> %s road links",
        Path(flood_path).name,
        before,
        len(filtered),
    )
    if filtered.empty:
        logging.warning(
            "Raster extent prefilter found no road links for %s; downstream output may be empty.",
            flood_path,
        )
    return filtered


def load_analysis_boundary(base_path: Path) -> gpd.GeoDataFrame:
    """Load study-area boundary (preferred) or fallback to a broad USA polygon."""
    study_area_path = first_existing(
        [
            base_path / "study_area" / "fairfax_study_area.gpkg",
            base_path / "study_area" / "fairfax_study_area.geojson",
            base_path / "inputs" / "study_area" / "fairfax_study_area.gpkg",
            base_path / "inputs" / "study_area" / "fairfax_study_area.geojson",
        ]
    )
    if study_area_path is not None:
        return gpd.read_file(study_area_path)

    from shapely.geometry import box

    continental = box(-125, 24, -66, 50)
    alaska = box(-170, 50, -130, 72)
    hawaii = box(-160, 18, -154, 23)
    usa_geom = continental.union(alaska).union(hawaii)
    return gpd.GeoDataFrame({"name": ["USA"]}, geometry=[usa_geom], crs="EPSG:4326")


def intersect_features_with_raster(
    raster_path: str,
    raster_key: str,
    features: gpd.GeoDataFrame,
    flood_type: str,
) -> gpd.GeoDataFrame:
    """
    Intersects vector features with a raster dataset to compute flood depth for each
        feature.

    Parameters:
        raster_path (str): Path to the raster file containing flood data.
        raster_key (str): Identifier for the raster dataset.
        features (gpd.GeoDataFrame): GeoDataFrame containing vector features (e.g.,
            road links).
        flood_type (str): Type of flood (e.g., "surface" or "river").

    Returns:
        gpd.GeoDataFrame: GeoDataFrame of intersected features with flood depth values,
                          reprojected to TARGET_CRS.
    """

    logging.info(f"Intersecting features with raster {raster_key}...")

    # Keep only columns needed downstream to reduce split/copy overhead substantially
    required_cols = ["e_id", "road_classification", "trunk_road", "road_label", "geometry"]
    present_cols = [c for c in required_cols if c in features.columns]
    features_min = features[present_cols].copy()

    # Ensure expected optional columns exist for damage logic
    if "trunk_road" not in features_min.columns:
        features_min["trunk_road"] = None
    if "road_label" not in features_min.columns:
        features_min["road_label"] = None

    # Avoid pandas extension/Arrow string dtypes that can interact badly with
    # snail's row-wise splitting on large datasets.
    for col in [c for c in features_min.columns if c != "geometry"]:
        if str(features_min[col].dtype).startswith("string"):
            features_min[col] = features_min[col].astype(object)

    # run the intersection analysis using a windowed raster read
    prepared = intersection.prepare_linestrings(features_min)

    with rasterio_env():
        with rasterio.open(raster_path) as dataset:
            grid_result = build_snail_grid(dataset, prepared, target_crs=TARGET_CRS)
            prepared = grid_result.prepared
            grid = grid_result.grid
            raster = grid_result.raster

    if prepared.empty:
        return prepared

    if SPLIT_SIMPLIFY_TOLERANCE_M > 0:
        prepared = prepared.copy()
        prepared["geometry"] = prepared.geometry.simplify(
            SPLIT_SIMPLIFY_TOLERANCE_M,
            preserve_topology=True,
        )

    cache_key = None
    intersections = None
    if ENABLE_SPLIT_CACHE and "e_id" in prepared.columns:
        try:
            eids = prepared["e_id"].astype(str).tolist()
            cache_key = (
                tuple(sorted(eids)),
                grid.crs,
                grid.width,
                grid.height,
                tuple(grid.transform),
                round(float(SPLIT_SIMPLIFY_TOLERANCE_M), 6),
            )
            cached = _SPLIT_CACHE.get(cache_key)
            if cached is not None:
                intersections = cached.copy()
        except Exception:
            cache_key = None

    if intersections is None:
        intersections = intersection.split_linestrings(prepared, grid)
        intersections = intersection.apply_indices(intersections, grid)
        if cache_key is not None:
            _SPLIT_CACHE[cache_key] = intersections.copy()

    intersections[f"flood_depth_{flood_type}"] = (
        intersection.get_raster_values_for_splits(intersections, raster)
    )

    # reproject back
    try:
        intersections = intersections.to_crs(TARGET_CRS)
    except Exception as e:
        raise RuntimeError(
            f"Failed to reproject intersections to {TARGET_CRS}. "
            "Aborting to avoid CRS ambiguity in downstream damage calculations. "
            f"Details: {e}"
        )
    intersections["length"] = intersections.geometry.length

    return intersections


def clip_features(
    features: gpd.GeoDataFrame,
    clip_path: Optional[str],
    raster_key: str,
    boundary_gdf: Optional[gpd.GeoDataFrame] = None,
) -> gpd.GeoDataFrame:
    """
    Clips spatial features to the extent of a specified vector layer.

    Parameters:
        features (gpd.GeoDataFrame): GeoDataFrame containing the spatial features to be
            clipped.
        clip_path (str): Path to the vector file used for clipping.
        raster_key (str): Identifier for the raster dataset.

    Returns:
        gpd.GeoDataFrame: GeoDataFrame of features clipped to the extent of the clip
            layer.
    """

    logging.info(f"Clipping features based on {raster_key}...")
    skip_vector_clip = False
    clips = None
    if clip_path is None:
        skip_vector_clip = True
        logging.warning(
            "No clip vector provided; proceeding with boundary-only clipping."
        )
    else:
        clips = gpd.read_file(clip_path, engine="pyogrio")  # grid's extent (vector)
        clips = clips.reset_index(drop=True)  # Ensure no 'index_right' column conflicts

    # Temporary QA guard: some Aqueduct vector masks are global extent polygons
    # ([-180, -90, 180, 90] in EPSG:4326). Reprojecting this footprint to EPSG:2163
    # can collapse around the antimeridian and unintentionally clip out most links.
    if clips is not None and clips.crs is not None and str(clips.crs).upper().endswith("4326"):
        minx, miny, maxx, maxy = clips.total_bounds
        if (
            abs(minx + 180) < 1e-6
            and abs(miny + 90) < 1e-6
            and abs(maxx - 180) < 1e-6
            and abs(maxy - 90) < 1e-6
        ):
            skip_vector_clip = True
            logging.warning(
                "Global vector extent detected; skipping vector clipping for QA run."
            )
    
    # Store original columns to preserve
    original_columns = features.columns.tolist()
    
    # Reproject the clip shapefile only when it will be used for spatial clipping
    if (not skip_vector_clip) and clips is not None and clips.crs != features.crs:
        logging.info("Projecting Shapefile CRS to match Feature CRS...")
        clips = clips.to_crs(features.crs)

    if boundary_gdf is not None:
        if boundary_gdf.crs != features.crs:
            boundary_gdf = boundary_gdf.to_crs(features.crs)
        boundary_gdf = boundary_gdf.reset_index(drop=True)
        features = gpd.sjoin(features, boundary_gdf, how="inner", predicate="intersects")
        # Keep only original columns from features
        features = features[[col for col in original_columns if col in features.columns]]

    if skip_vector_clip:
        clipped_features = features.copy()
    else:
        clipped_features = gpd.sjoin(features, clips, how="inner", predicate="intersects")
    # Keep only original columns from features
    clipped_features = clipped_features[[col for col in original_columns if col in clipped_features.columns]]
    clipped_features.reset_index(drop=True, inplace=True)
    return clipped_features