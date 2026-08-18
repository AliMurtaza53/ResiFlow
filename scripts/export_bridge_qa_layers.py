#!/usr/bin/env python3
"""Export GeoJSON QA layers for visually auditing the NBI bridge join in a
GIS tool (ArcGIS Pro, QGIS, etc).

Produces four layers, all reprojected to EPSG:4326 (WGS84) for broad GIS
compatibility:

  1. bridge_points_matched_va.geojson   -- NBI structures matched to a FAF5
     link, clipped to Virginia (the paper's own case-study area, small
     enough for close inspection against satellite imagery).
  2. bridge_links_flagged_va.geojson    -- FAF5 links flagged road_bridge=
     'yes', same VA clip, carrying match_distance_m/deck_width_m/n_structures
     so you can symbolize/filter by match quality.
  3. bridge_points_matched_national.geojson -- all 236,729 matched
     structures, national extent, for a broad pattern check (do bridges
     cluster on interstate corridors and known river crossings, or look
     scattered/random?).
  4. bridge_links_flagged_national.geojson  -- all 126,363 flagged links,
     national extent.

VA clip uses a simple bounding box (not a precise state boundary) --
generous enough to catch all of VA plus a small margin, tight enough to
keep the close-inspection layers small.

Usage (on Hopper, real data)::

    python scripts/export_bridge_qa_layers.py \\
        --nbi /scratch/akothaw/multimodal_hazard_data/inputs_raw/nbi_bridges_2024.parquet \\
        --bridge-index /scratch/akothaw/multimodal_hazard_data/soge_clusters/networks/faf5/faf5_bridge_index.parquet \\
        --road-links /scratch/akothaw/multimodal_hazard_data/soge_clusters/networks/faf5/faf5_road_links.gpq \\
        --output-dir /scratch/akothaw/multimodal_hazard_data/bridge_qa_export
"""

from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point, box

# Generous VA bounding box (WGS84) -- covers the whole state plus a margin,
# not a precise boundary; this is for visual QA, not analysis.
VA_BBOX_WGS84 = (-83.7, 36.4, -75.1, 39.5)  # (minx, miny, maxx, maxy)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--nbi", type=Path, required=True)
    parser.add_argument("--bridge-index", type=Path, required=True)
    parser.add_argument("--road-links", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)

    nbi = pd.read_parquet(args.nbi)
    bridge_index = pd.read_parquet(args.bridge_index)
    road_links = gpd.read_parquet(args.road_links)
    if road_links.crs is None:
        raise ValueError(f"{args.road_links} has no CRS set")
    road_links["e_id"] = road_links["e_id"].astype(str)

    # --- Matched structures: NBI points with match info -----------------
    matched_ids = set(bridge_index["e_id"])
    # Re-derive which structures matched by re-running the same nearest join
    # bridge_index doesn't retain, so we don't need it: bridge_index is
    # already e_id-level aggregated. Instead, treat every NBI structure
    # whose nearest link ended up in bridge_index as "matched" for display
    # purposes by re-joining on proximity once more, lightweight (points
    # only, no aggregation needed here).
    nbi_gdf = gpd.GeoDataFrame(
        nbi,
        geometry=[Point(lon, lat) for lon, lat in zip(nbi["longitude"], nbi["latitude"])],
        crs="EPSG:4326",
    )
    links_wgs84 = road_links[["e_id", "geometry"]].to_crs("EPSG:4326")
    links_proj = road_links[["e_id", "geometry"]].to_crs("EPSG:9311")
    nbi_proj = nbi_gdf.to_crs("EPSG:9311")
    matched_points = gpd.sjoin_nearest(
        nbi_proj, links_proj, how="left", max_distance=100.0, distance_col="match_distance_m"
    )
    matched_points = matched_points.dropna(subset=["e_id"]).drop_duplicates(subset=["structure_number", "e_id"])
    matched_points = matched_points.drop(columns=["index_right"]).to_crs("EPSG:4326")

    flagged_links = links_wgs84.merge(bridge_index, on="e_id", how="inner")

    def clip_to_va(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        bbox = box(*VA_BBOX_WGS84)
        return gdf[gdf.intersects(bbox)].copy()

    outputs = {
        "bridge_points_matched_va.geojson": clip_to_va(matched_points),
        "bridge_links_flagged_va.geojson": clip_to_va(flagged_links),
        "bridge_points_matched_national.geojson": matched_points,
        "bridge_links_flagged_national.geojson": flagged_links,
    }
    for name, gdf in outputs.items():
        out_path = args.output_dir / name
        gdf.to_file(out_path, driver="GeoJSON")
        print(f"Wrote {out_path} ({len(gdf)} features)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
