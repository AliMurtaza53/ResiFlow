"""Cheap-checks after splice_hpms_la_network.py — fail closed before SLURM."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

ROOT = Path("/scratch/akothaw/multimodal_hazard_data/scratch_tests/hpms_la_challenger")
ISO = ROOT / "isolated_base"
V3 = Path(
    "/scratch/akothaw/multimodal_hazard_data/scratch_tests/county_connector_remedy/v3_vehicle_trips"
)
SOGE = Path("/scratch/akothaw/multimodal_hazard_data/soge_clusters")


def main() -> int:
    man = json.loads((ROOT / "splice_manifest.json").read_text())
    od_new = pd.read_parquet(man["od_path"])
    od_old = pd.read_parquet(V3 / "passenger_od_multinode_v3.pq")

    print("CHECK 1: demand conservation")
    d0, d1 = float(od_old["Car21"].sum()), float(od_new["Car21"].sum())
    print(f"  Car21 before={d0:.6f} after={d1:.6f} diff={abs(d0-d1):.2e}")
    assert abs(d0 - d1) < 1e-6
    assert len(od_old) == len(od_new)
    print("  PASS")

    print("CHECK 2: LA remaps present in OD and as network nodes")
    links = gpd.read_parquet(ISO / "networks/faf5/faf5_road_links.gpq")
    nodes = gpd.read_parquet(ISO / "networks/faf5/faf5_road_nodes.gpq")
    node_ids = set(nodes["node_id"].astype(int))
    for label, mp in (("home", man["home_map"]), ("work", man["work_map"])):
        for old, new in mp.items():
            nid = int(new)
            assert nid in node_ids, f"centroid {nid} missing from road_nodes"
            col = "origin_node" if label == "home" else "destination_node"
            n = (od_new[col].astype(str) == str(nid)).sum()
            assert n > 0, f"no OD rows with {col}={nid}"
            print(f"  {label} {old}->{nid}: {n} OD rows")
    print("  PASS")

    print("CHECK 3: connector edges exist; mid-node degree plausible")
    conn = links[links["e_id"].astype(str).str.startswith("conn_")]
    assert len(conn) > 0
    # each centroid should have 2*k directed connector edges
    for key, info in man["id_map"].items():
        cid = int(info["centroid_id"])
        deg = ((links["from_id"] == cid) | (links["to_id"] == cid)).sum()
        n_conn = len(info.get("connectors", []))
        # bidirectional => 2 edges per connector
        assert deg == 2 * n_conn, f"{key} centroid degree {deg} != {2*n_conn}"
        print(f"  {key}: {n_conn} connectors, degree={deg}")
    print("  PASS")

    print("CHECK 4: no duplicate route_id among a centroid's attachments")
    for key, info in man["id_map"].items():
        routes = [c.get("route_id") for c in info.get("connectors", []) if c.get("route_id")]
        if routes:
            assert len(routes) == len(set(routes)), f"{key} duplicate route_id {routes}"
    print("  PASS")

    print("CHECK 5: shared soge_clusters untouched (size)")
    for name in ("faf5_road_links.gpq", "faf5_road_nodes.gpq"):
        p = SOGE / "networks/faf5" / name
        # just ensure file still readable / non-empty
        assert p.stat().st_size > 1_000_000, p
        print(f"  {name} size={p.stat().st_size}")
    print("  PASS")

    print("CHECK 6: network growth sanity")
    print(
        f"  links {man['orig_links']} -> {man['n_links']} "
        f"(+{man['n_links']-man['orig_links']}); "
        f"xfer_edges={man['n_xfer_edges']}"
    )
    assert man["n_links"] > man["orig_links"]
    assert man["n_xfer_edges"] > 0, "no FAF5↔HPMS transfers — HPMS would be an island"
    print("  PASS")

    print("\nALL CHEAP-CHECKS PASSED")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        raise SystemExit(1)
