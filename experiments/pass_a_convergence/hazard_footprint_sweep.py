#!/usr/bin/env python3
"""Goal 5: damaged-link counts for 30m vs 90m vs expanded footprint on CONUS links in raster extent."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.transform import Affine
from rasterio.warp import reproject, Resampling as WarpResampling

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from resiflow.exposure.raster_line import (
    intersect_features_with_raster,
    subset_features_to_raster_extent,
)
from resiflow.fragility.flood_categorical import compute_damage_levels_on_flooded_roads_vectorized

RUNS_ROOT = Path(__file__).resolve().parent / "runs"
VA_RASTER = Path(r"C:/Users/akothaw/Desktop/data/soge_clusters/inputs/test_141node_50m/va_hazard_class50_141node_base.tif")
CONUS_LINKS = Path(r"C:/Users/akothaw/Desktop/data/soge_clusters/networks/faf5/faf5_road_links.gpq")


def _resample_raster(src_path: Path, out_path: Path, *, factor: float) -> dict:
    with rasterio.open(src_path) as src:
        new_w = max(1, int(src.width * factor))
        new_h = max(1, int(src.height * factor))
        data = np.empty((new_h, new_w), dtype=src.dtypes[0])
        transform = src.transform * src.transform.scale(src.width / new_w, src.height / new_h)
        reproject(
            source=rasterio.band(src, 1),
            destination=data,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=transform,
            dst_crs=src.crs,
            resampling=WarpResampling.max,
        )
        profile = src.profile.copy()
        profile.update(width=new_w, height=new_h, transform=transform)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(out_path, "w", **profile) as dst:
            dst.write(data, 1)
        bounds = rasterio.transform.array_bounds(new_h, new_w, transform)
        return {"area_deg2": (bounds[2] - bounds[0]) * (bounds[3] - bounds[1])}


def _expand_raster(src_path: Path, out_path: Path, *, pad_factor: float = 1.5) -> dict:
    with rasterio.open(src_path) as src:
        data = src.read(1)
        h, w = data.shape
        pad_x = int(w * (pad_factor - 1) / 2)
        pad_y = int(h * (pad_factor - 1) / 2)
        padded = np.zeros((h + 2 * pad_y, w + 2 * pad_x), dtype=data.dtype)
        padded[pad_y : pad_y + h, pad_x : pad_x + w] = data
        transform = src.transform * Affine.translation(-pad_x, -pad_y)
        profile = src.profile.copy()
        profile.update(width=padded.shape[1], height=padded.shape[0], transform=transform)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(out_path, "w", **profile) as dst:
            dst.write(padded, 1)
        bounds = rasterio.transform.array_bounds(padded.shape[0], padded.shape[1], transform)
        return {"area_deg2": (bounds[2] - bounds[0]) * (bounds[3] - bounds[1])}


def _count_links(links: gpd.GeoDataFrame, raster_path: Path) -> dict:
    subset = subset_features_to_raster_extent(links, str(raster_path))
    if subset.empty:
        return {"links_in_extent": 0, "exposed_links": 0, "damaged_links": 0}
    intersections = intersect_features_with_raster(
        str(raster_path), raster_path.stem, subset, "flood"
    )
    if intersections.empty or "flood_depth_flood" not in intersections.columns:
        return {
            "links_in_extent": int(subset["e_id"].nunique()),
            "exposed_links": 0,
            "damaged_links": 0,
        }
    depth = intersections["flood_depth_flood"].fillna(0)
    exposed = int(intersections.loc[depth > 0, "e_id"].nunique())
    damage = compute_damage_levels_on_flooded_roads_vectorized(
        "flood",
        intersections["road_classification"],
        intersections.get("trunk_road", False),
        intersections.get("road_label", ""),
        depth,
    )
    damaged = int(intersections.loc[damage.astype(str).str.lower() != "no", "e_id"].nunique())
    return {
        "links_in_extent": int(subset["e_id"].nunique()),
        "exposed_links": exposed,
        "damaged_links": damaged,
    }


def main() -> int:
    if not VA_RASTER.exists() or not CONUS_LINKS.exists():
        raise SystemExit("Missing VA raster or CONUS links bundle")

    links = gpd.read_parquet(CONUS_LINKS)
    if links.crs is None:
        links = links.set_crs("EPSG:4326")

    with tempfile.TemporaryDirectory(prefix="goal5_ras_") as tmp:
        ras_path = Path(tmp)
        raster_90 = ras_path / "va_hazard_90m_same_extent.tif"
        raster_90_large = ras_path / "va_hazard_90m_expanded.tif"
        meta_90 = _resample_raster(VA_RASTER, raster_90, factor=30 / 90)
        meta_large = _expand_raster(VA_RASTER, raster_90_large, pad_factor=1.5)

        rows = []
        for label, path, meta in (
            ("A_30m_original", VA_RASTER, {"resolution_note": "toy ~50m native cell"}),
            ("B_90m_same_extent", raster_90, meta_90),
            ("C_90m_expanded_footprint", raster_90_large, meta_large),
        ):
            counts = _count_links(links, path)
            rows.append({"scenario": label, **meta, **counts})

    out = {"network": "conus_faf5_subset_to_raster", "raster_source": str(VA_RASTER), "rows": rows}
    RUNS_ROOT.mkdir(parents=True, exist_ok=True)
    out_path = RUNS_ROOT / "goal5_hazard_footprint.json"
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
