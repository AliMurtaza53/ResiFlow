"""ADD-ONLY splice: FAF5 + mid-noded HPMS-LA + unique-segment centroid connectors.

Runs on Hopper. Writes into an isolated hardlink tree (caller must cp -al +
rm target gpq files first). Relabels LA OD origins/destinations onto new
centroid node string ids.

ponytail: FAF5↔HPMS join = short transfer edges where nodes are ≤ XFER_M apart
(LA bbox only). No national rebuild.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely import STRtree
from shapely.geometry import LineString, Point

sys.path.insert(0, "/scratch/akothaw/multimodal_hazard_data/code/ResiFlow/src")
from resiflow.preprocess.network_connector_insertion import (  # noqa: E402
    build_bidirectional_connector,
    is_eligible_attachment_edge,
    split_edge_at_fraction,
)

ROOT = Path("/scratch/akothaw/multimodal_hazard_data/scratch_tests/hpms_la_challenger")
ART = ROOT / "artifacts"
ISO = ROOT / "isolated_base"
SOGE_ORIG = Path("/scratch/akothaw/multimodal_hazard_data/soge_clusters")
V3 = Path(
    "/scratch/akothaw/multimodal_hazard_data/scratch_tests/county_connector_remedy/v3_vehicle_trips"
)

XFER_M = 30.0
CENTROID_ID_BASE = 600_000
NETWORK_CRS = "EPSG:9311"


def _align_columns(add: gpd.GeoDataFrame, template: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    out = add.copy()
    for col in template.columns:
        if col not in out.columns:
            out[col] = pd.NA
    # keep extra HPMS provenance cols if present
    return out


def _la_bbox_native(links: gpd.GeoDataFrame) -> tuple[float, float, float, float]:
    # rough LA county WGS84 bbox → native
    from shapely.geometry import box

    b = gpd.GeoSeries([box(-118.951721, 32.75004, -117.646374, 34.823302)], crs="EPSG:4326").to_crs(
        links.crs
    ).iloc[0].bounds
    return b


def build_transfer_edges(
    faf_nodes: gpd.GeoDataFrame,
    hpms_nodes: gpd.GeoDataFrame,
    *,
    start_e: int,
) -> tuple[list[dict], int]:
    """Bidirectional transfer edges for HPMS↔FAF node pairs within XFER_M."""
    faf = faf_nodes.copy()
    bbox = _la_bbox_native(faf.set_crs(faf.crs) if faf.crs else faf)
    # filter FAF nodes to LA bbox
    faf = faf.cx[bbox[0]:bbox[2], bbox[1]:bbox[3]]
    if faf.empty or hpms_nodes.empty:
        return [], start_e

    tree = STRtree(faf.geometry.values)
    faf_ids = faf["node_id"].to_numpy()
    faf_geoms = list(faf.geometry.values)

    rows = []
    e = start_e
    seen: set[tuple[int, int]] = set()
    for _, hn in hpms_nodes.iterrows():
        idxs = tree.query(hn.geometry.buffer(XFER_M))
        if len(idxs) == 0:
            continue
        best_i, best_d = None, float("inf")
        for j in idxs:
            d = faf_geoms[int(j)].distance(hn.geometry)
            if d < best_d:
                best_d, best_i = d, int(j)
        if best_i is None or best_d > XFER_M:
            continue
        fid = int(faf_ids[best_i])
        hid = int(hn["node_id"])
        key = (min(fid, hid), max(fid, hid))
        if key in seen:
            continue
        seen.add(key)
        a = faf_geoms[best_i]
        b = hn.geometry
        geom = LineString([(a.x, a.y), (b.x, b.y)])
        length = float(geom.length)
        if length <= 0:
            # coincident: still need a logical link — tiny epsilon length
            length = 0.1
            geom = LineString([(a.x, a.y), (a.x + 0.1, a.y)])
        for frm, to, suffix, g in (
            (hid, fid, "ab", geom),
            (fid, hid, "ba", LineString(list(geom.coords)[::-1])),
        ):
            rows.append(
                {
                    "e_id": f"xfer_{e}_{suffix}",
                    "from_id": frm,
                    "to_id": to,
                    "geometry": g,
                    "length": length,
                    "assignment_tier": "arterial",
                    "network_source": "hpms_faf_xfer",
                    "lanes": 2,
                    "Speed_Limit": 45.0,
                    "average_toll_cost": 0.0,
                    "road_bridge": "no",
                    "road_tunnel": "no",
                    "bridge_fraction": 0.0,
                    "tunnel_fraction": 0.0,
                    "road_label": "road",
                    "oneway": False,
                }
            )
        e += 1
    return rows, e


def insert_centroids(
    links: gpd.GeoDataFrame,
    nodes: gpd.GeoDataFrame,
    probe_rows: list[dict],
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, dict]:
    """Insert unique-segment connectors from probe; return links, nodes, id map."""
    next_id = CENTROID_ID_BASE
    id_map = {}  # (endpoint, rank) -> {"centroid_id": int, "old_faf_node": int}
    new_node_rows = []
    drop_eids: set[str] = set()
    add_edge_rows: list[pd.Series | dict] = []

    # template edge for connector schema fill
    template = links.iloc[0]

    for r in probe_rows:
        endpoint = r["endpoint"]
        rank = int(r["subarea_rank"])
        old = int(r["faf5_node_id"])
        centroid_id = next_id
        next_id += 1
        lon, lat = r["centroid_lonlat"]
        c_native = (
            gpd.GeoSeries([Point(lon, lat)], crs="EPSG:4326").to_crs(links.crs).iloc[0]
        )
        new_node_rows.append({"node_id": centroid_id, "geometry": c_native})
        id_map[f"{endpoint}:{rank}"] = {
            "centroid_id": centroid_id,
            "centroid_str": f"hpms_centroid_{endpoint}_{rank}",
            "old_faf_node": old,
            "endpoint": endpoint,
            "rank": rank,
        }

        for i, conn in enumerate(r["connectors_unique_segment"]):
            e_id = str(conn["e_id"])
            if e_id not in set(links["e_id"].astype(str)):
                raise ValueError(f"probe e_id {e_id} not in links")
            parent = links[links["e_id"].astype(str) == e_id].iloc[0]
            if not is_eligible_attachment_edge(parent):
                raise ValueError(f"attachment edge {e_id} failed eligibility")

            mid_id = next_id
            next_id += 1
            fraction = float(conn.get("fraction", 0.5))
            # clamp away from endpoints
            fraction = min(max(fraction, 0.15), 0.85)

            child_a, child_b = split_edge_at_fraction(links, e_id, fraction, mid_id)
            drop_eids.add(e_id)
            add_edge_rows.extend([child_a, child_b])

            # reverse twin if present
            rev = f"{e_id}_r"
            if rev in set(links["e_id"].astype(str)) and rev not in drop_eids:
                try:
                    ra, rb = split_edge_at_fraction(links, rev, 1.0 - fraction, mid_id)
                    drop_eids.add(rev)
                    add_edge_rows.extend([ra, rb])
                except ValueError as exc:
                    print(f"  skip reverse split {rev}: {exc}")

            mid_pt = Point(child_a.geometry.coords[-1])
            new_node_rows.append({"node_id": mid_id, "geometry": mid_pt})
            conn_geom = LineString([(c_native.x, c_native.y), (mid_pt.x, mid_pt.y)])
            for edge in build_bidirectional_connector(
                centroid_id,
                mid_id,
                geometry=conn_geom,
                e_id_prefix=f"conn_{endpoint}{rank}_{i}",
                template=template,
            ):
                add_edge_rows.append(edge)

            id_map[f"{endpoint}:{rank}"].setdefault("connectors", []).append(
                {
                    "mid_id": mid_id,
                    "e_id": e_id,
                    "route_id": conn.get("route_id"),
                    "length_m": float(conn_geom.length),
                }
            )

    # assemble links
    keep = links[~links["e_id"].astype(str).isin(drop_eids)].copy()
    add_df = gpd.GeoDataFrame(add_edge_rows, crs=links.crs)
    add_df = _align_columns(add_df, keep)
    links_out = pd.concat([keep, add_df], ignore_index=True)
    links_out = gpd.GeoDataFrame(links_out, geometry="geometry", crs=links.crs)

    nodes_out = pd.concat(
        [nodes, gpd.GeoDataFrame(new_node_rows, crs=nodes.crs)], ignore_index=True
    )
    nodes_out = gpd.GeoDataFrame(nodes_out, geometry="geometry", crs=nodes.crs)
    return links_out, nodes_out, id_map


def patch_od(id_map: dict) -> tuple[pd.DataFrame, dict, dict]:
    od = pd.read_parquet(V3 / "passenger_od_multinode_v3.pq").copy()
    od["origin_node"] = od["origin_node"].astype(str)
    od["destination_node"] = od["destination_node"].astype(str)
    before = float(od["Car21"].sum())

    home_map = {
        str(v["old_faf_node"]): str(v["centroid_id"])
        for v in id_map.values()
        if v["endpoint"] == "home"
    }
    work_map = {
        str(v["old_faf_node"]): str(v["centroid_id"])
        for v in id_map.values()
        if v["endpoint"] == "work"
    }
    od["origin_node"] = od["origin_node"].replace(home_map)
    od["destination_node"] = od["destination_node"].replace(work_map)
    after = float(od["Car21"].sum())
    if abs(before - after) > 1e-6:
        raise ValueError(f"OD demand not conserved: {before} -> {after}")
    return od, home_map, work_map


def main() -> int:
    print("Loading FAF5 (read-only original)...", flush=True)
    links = gpd.read_parquet(SOGE_ORIG / "networks/faf5/faf5_road_links.gpq")
    nodes = gpd.read_parquet(SOGE_ORIG / "networks/faf5/faf5_road_nodes.gpq")
    print(f"  FAF5 {len(links)} links, {len(nodes)} nodes, CRS={links.crs}")

    print("Loading HPMS-LA noded...", flush=True)
    hpms_l = gpd.read_parquet(ART / "hpms_la_links_noded.parquet")
    hpms_n = gpd.read_parquet(ART / "hpms_la_nodes_noded.parquet")
    # Force identical CRS object (same EPSG:9311 can differ by PROJ name and
    # break GeoPandas concat).
    hpms_l = hpms_l.to_crs(links.crs)
    hpms_n = hpms_n.to_crs(links.crs)
    hpms_l = hpms_l.set_crs(links.crs, allow_override=True)
    hpms_n = hpms_n.set_crs(links.crs, allow_override=True)
    print(f"  HPMS {len(hpms_l)} links, {len(hpms_n)} nodes")

    # ensure from_id/to_id int
    hpms_l["from_id"] = hpms_l["from_id"].astype(int)
    hpms_l["to_id"] = hpms_l["to_id"].astype(int)
    hpms_n["node_id"] = hpms_n["node_id"].astype(int)
    if "average_toll_cost" not in hpms_l.columns:
        hpms_l["average_toll_cost"] = 0.0
    hpms_l["average_toll_cost"] = pd.to_numeric(hpms_l["average_toll_cost"], errors="coerce").fillna(0.0)

    print("Building FAF5↔HPMS transfer edges...", flush=True)
    xfer_rows, _ = build_transfer_edges(nodes, hpms_n, start_e=0)
    print(f"  transfer pairs: {len(xfer_rows)//2}")

    print("Concatenating networks...", flush=True)
    target_crs = links.crs
    # Strip CRS metadata before concat — same EPSG:9311 can carry different
    # PROJ names and GeoPandas refuses to merge them.
    for gdf in (links, nodes, hpms_l, hpms_n):
        gdf.set_crs(None, allow_override=True, inplace=True)
    hpms_l = _align_columns(hpms_l, links)
    xfer_gdf = gpd.GeoDataFrame(xfer_rows, crs=None) if xfer_rows else gpd.GeoDataFrame(geometry=[], crs=None)
    parts = [links, hpms_l]
    if len(xfer_gdf):
        xfer_gdf = _align_columns(xfer_gdf, links)
        parts.append(xfer_gdf)
    links2 = gpd.GeoDataFrame(
        pd.concat(parts, ignore_index=True),
        geometry="geometry",
        crs=target_crs,
    )
    nodes2 = gpd.GeoDataFrame(
        pd.concat([nodes, hpms_n], ignore_index=True),
        geometry="geometry",
        crs=target_crs,
    )
    assert nodes2["node_id"].is_unique, "node_id collision after HPMS append"
    assert links2["e_id"].astype(str).is_unique, "e_id collision after HPMS append"

    probe = json.loads((ART / "enclosing_connector_probe.json").read_text())
    # one attachment e_id may not appear twice across the 12 centroids
    all_attach = [
        str(c["e_id"])
        for r in probe["rows"]
        for c in r["connectors_unique_segment"]
    ]
    if len(all_attach) != len(set(all_attach)):
        raise ValueError(f"duplicate attachment e_ids in probe: {all_attach}")

    print("Inserting 12 centroids + unique-segment connectors...", flush=True)
    links3, nodes3, id_map = insert_centroids(links2, nodes2, probe["rows"])
    print(f"  final {len(links3)} links, {len(nodes3)} nodes")

    print("Patching OD...", flush=True)
    od, home_map, work_map = patch_od(id_map)
    print(f"  home remaps {home_map}")
    print(f"  work remaps {work_map}")
    print(f"  OD rows {len(od)}, Car21={od['Car21'].sum():.3f}")

    # Write into isolated tree (must already exist with gpq removed)
    out_links = ISO / "networks/faf5/faf5_road_links.gpq"
    out_nodes = ISO / "networks/faf5/faf5_road_nodes.gpq"
    if out_links.exists() or out_nodes.exists():
        raise SystemExit(
            f"refusing to overwrite existing {out_links} / {out_nodes} — "
            "rm them first after cp -al (hardlink safety)"
        )
    out_links.parent.mkdir(parents=True, exist_ok=True)
    print(f"Writing {out_links} ...", flush=True)
    links3.to_parquet(out_links)
    print(f"Writing {out_nodes} ...", flush=True)
    nodes3.to_parquet(out_nodes)
    od_path = ROOT / "passenger_od_hpms_la.pq"
    od.to_parquet(od_path)
    manifest = {
        "isolated_base": str(ISO),
        "od_path": str(od_path),
        "n_links": len(links3),
        "n_nodes": len(nodes3),
        "n_xfer_edges": len(xfer_rows),
        "xfer_m": XFER_M,
        "id_map": id_map,
        "home_map": home_map,
        "work_map": work_map,
        "orig_links": len(links),
        "orig_nodes": len(nodes),
    }
    (ROOT / "splice_manifest.json").write_text(json.dumps(manifest, indent=2, default=str))
    print("wrote splice_manifest.json")

    # verify shared original untouched
    orig_l = (SOGE_ORIG / "networks/faf5/faf5_road_links.gpq").stat().st_size
    orig_n = (SOGE_ORIG / "networks/faf5/faf5_road_nodes.gpq").stat().st_size
    print(f"shared original sizes still links={orig_l} nodes={orig_n}")
    return 0


if __name__ == "__main__":
    # re-patch patch_od return type hint used as tuple
    raise SystemExit(main())
