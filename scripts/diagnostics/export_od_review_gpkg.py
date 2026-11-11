#!/usr/bin/env python3
"""Export the FAF5 network and the county OD centroids to GeoPackage for review in QGIS or ArcGIS Pro (all layers EPSG:4326).

Writes two files (the network is big, the centroid review file is small):
  faf5_network_links.gpkg      layer network_links_current   (483,599 links, current numbering, key attributes only)
  resiflow_od_review.gpkg      layers:
    faf5_loading_centroids       the FAF5 network's own loading centroids (FAF5Network.gdb FAF5_Nodes, Centroid=1)
    counties_tiger_simplified    TIGER 2022 county polygons (simplified for display)
    county_centroids_tiger       the TIGER county centroids (the builder's fallback reference points)
    od_node_intended             where the OD builder INTENDED each county's node: the OD node id located in the nodes file the
                                 builder used (old numbering). Attributes carry the builder's own crosswalk record.
    od_node_as_run               where the model actually injects the demand today: the SAME node id located in the current network
                                 (the nodes file that matches the current links). If the two numberings agreed this layer would
                                 coincide with od_node_intended; it does not.
    od_node_corrected            the corrected snap (current numbering), conterminous counties only
    line_intended_to_as_run      3,144 lines joining intended -> as-run position of the same node id (the size of the mismatch)
    line_intended_to_corrected   short lines joining intended -> corrected node (the size of the re-snap)

Inputs are the local copies under Desktop\\data (see --help). Nothing is modified.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from shapely.geometry import LineString

LINK_COLS = ["e_id", "from_id", "to_id", "Road_Name", "STATE", "County_Name", "assignment_tier", "faf5_class", "lanes", "length_mile", "road_bridge", "road_tunnel"]


def nodes_xy(path: Path) -> gpd.GeoDataFrame:
    g = gpd.read_parquet(path)
    g["node_id"] = g["node_id"].astype("int64")
    return g.set_index("node_id")


def points_at(nodes: gpd.GeoDataFrame, ids: pd.Series) -> gpd.GeoSeries:
    geo = nodes.geometry.reindex(ids.astype("int64").to_numpy())
    return gpd.GeoSeries(geo.values, crs=nodes.crs).to_crs(4326)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    d = "C:/Users/akothaw/Desktop/data"
    ap.add_argument("--links", default=f"{d}/soge_clusters/networks/faf5/faf5_road_links.bridge_tunnel_patched_hopper_2026-10-23.gpq")
    ap.add_argument("--nodes-current", default=f"{d}/soge_clusters/networks/faf5/faf5_road_nodes.hopper_2026-10-23.gpq")
    ap.add_argument("--nodes-od", default=f"{d}/soge_clusters/networks/faf5/faf5_road_nodes.gpq", help="nodes file in the numbering the OD builder used")
    ap.add_argument("--crosswalk-built", default=f"{d}/faf5_data/processed/bts_county_to_network_centroid_crosswalk_2022.csv")
    ap.add_argument("--crosswalk-corrected", default="parameters/crosswalks/county_node_crosswalk_conterminous.csv")
    ap.add_argument("--loading-centroids", default=f"{d}/faf5_data/processed/faf5_network_loading_centroids.gpq")
    ap.add_argument("--county-shp", default=f"{d}/faf5_data/county_shp/tl_2022_us_county.shp")
    ap.add_argument("--out-dir", default="C:/Users/akothaw/Desktop/gis_review")
    ap.add_argument("--skip-network", action="store_true")
    a = ap.parse_args()
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    # ---- network
    if not a.skip_network:
        names = pq.ParquetFile(a.links).schema_arrow.names
        links = gpd.read_parquet(a.links, columns=[c for c in LINK_COLS if c in names] + ["geometry"]).to_crs(4326)
        links.to_file(out / "faf5_network_links.gpkg", layer="network_links_current", driver="GPKG", engine="pyogrio")
        print(f"network_links_current: {len(links):,} links -> faf5_network_links.gpkg")

    rev = out / "resiflow_od_review.gpkg"
    if rev.exists():
        rev.unlink()

    def write(gdf: gpd.GeoDataFrame, layer: str) -> None:
        gdf.to_file(rev, layer=layer, driver="GPKG", engine="pyogrio")
        print(f"{layer}: {len(gdf):,} features")

    # ---- FAF5 loading centroids
    lc = gpd.read_parquet(a.loading_centroids).to_crs(4326)
    write(lc[[c for c in ("ID", "DATA", "CentroidID", "StateID", "StateName", "FAFID", "geometry") if c in lc.columns]], "faf5_loading_centroids")

    # ---- TIGER counties
    ct = gpd.read_file(a.county_shp)
    ct["GEOID"] = ct["GEOID"].astype(str).str.zfill(5)
    proj = ct.to_crs(5070)
    cc = gpd.GeoDataFrame(ct[["GEOID", "NAME", "STATEFP"]].copy(), geometry=proj.geometry.centroid, crs=5070).to_crs(4326)
    poly = ct[["GEOID", "NAME", "STATEFP", "geometry"]].to_crs(4326)
    poly["geometry"] = poly.geometry.simplify(0.01)
    write(poly, "counties_tiger_simplified")
    write(cc, "county_centroids_tiger")
    names_by = ct.set_index("GEOID").NAME

    # ---- OD nodes: intended (old numbering), as run (current numbering), corrected
    cwb = pd.read_csv(a.crosswalk_built, dtype=str)
    cwb["county_fips"] = cwb.detail_zone_id
    cwb["node_old"] = cwb.assigned_node_id.astype("int64")
    na = nodes_xy(Path(a.nodes_od))
    nc = nodes_xy(Path(a.nodes_current))
    cwb["county_name"] = cwb.county_fips.map(names_by)
    cwb["state_fips"] = cwb.county_fips.str[:2]
    base = cwb[["county_fips", "county_name", "state_fips", "assigned_centroid", "assignment_method", "distance_miles", "warning_flag"]].copy()
    base["node_id_old"] = cwb.node_old.to_numpy()
    intended = gpd.GeoDataFrame(base, geometry=points_at(na, cwb.node_old).values, crs=4326)
    as_run = gpd.GeoDataFrame(base, geometry=points_at(nc, cwb.node_old).values, crs=4326)
    km = lambda p, q: p.to_crs(5070).distance(q.to_crs(5070)) / 1000.0
    as_run["km_from_intended"] = km(as_run.geometry, intended.geometry).round(1).to_numpy()
    write(intended, "od_node_intended")
    write(as_run, "od_node_as_run")
    lines = intended[["county_fips", "county_name", "state_fips", "node_id_old"]].copy()
    lines["geometry"] = [LineString([p, q]) for p, q in zip(intended.geometry, as_run.geometry)]
    lines["km"] = as_run.km_from_intended.to_numpy()
    write(gpd.GeoDataFrame(lines, geometry="geometry", crs=4326), "line_intended_to_as_run")

    corr = pd.read_csv(a.crosswalk_corrected, dtype=str)
    corr["node_new"] = corr.node_id.astype("int64")
    m = corr.merge(cwb[["county_fips", "node_old"]], on="county_fips", how="left")
    cpts = points_at(nc, m.node_new)
    ipts = points_at(na, m.node_old)
    m["county_name"] = m.county_fips.map(names_by)
    m["snap_km"] = (cpts.to_crs(5070).distance(ipts.to_crs(5070)) / 1000.0).round(3).to_numpy()
    corrected = gpd.GeoDataFrame(m[["county_fips", "county_name", "state_fips", "node_old", "node_new", "snap_km"]], geometry=cpts.values, crs=4326)
    write(corrected, "od_node_corrected")
    cl = corrected[["county_fips", "county_name", "state_fips", "snap_km"]].copy()
    cl["geometry"] = [LineString([p, q]) for p, q in zip(ipts, cpts)]
    write(gpd.GeoDataFrame(cl, geometry="geometry", crs=4326), "line_intended_to_corrected")
    print(f"\nwrote {rev}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
