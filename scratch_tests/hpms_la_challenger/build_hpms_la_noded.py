"""Attributed mid-segment noding for lane-valid LA HPMS (challenger session 1b).

Takes the endpoint-noded artifacts (already clipped, lanes-valid), planar-nodes
them via unary_union, recovers attributes by midpoint→parent edge lookup, and
writes a directed assignment-ready graph.

Locals (f_system=7) are absent here because through_lanes is 100% null on them
in HPMS 2024 Full Extent for LA — inventing lanes would poison the comparison.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely import force_2d, STRtree
from shapely.geometry import LineString, MultiLineString, Point

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from resiflow.hpms_fclass import assignment_tier_from_fclass  # noqa: E402

ART = Path(__file__).resolve().parent / "artifacts"
NETWORK_CRS = "EPSG:9311"
SNAP_M = 1.0
NODE_ID_BASE = 500_000
EDGE_ID_PREFIX = "hpmsn_"

_ATTR_COLS = [
    "network_source",
    "hpms_fclass",
    "assignment_tier",
    "lanes",
    "Speed_Limit",
    "nhs_designation",
    "road_bridge",
    "road_tunnel",
    "road_label",
    "bridge_fraction",
    "tunnel_fraction",
    "Road_Name",
    "route_id",
    "begin_point",
    "end_point",
    "faf5_class",
    "oneway",
    "County_Name",
    "STATE",
]


def _segments(geom):
    if geom is None or geom.is_empty:
        return
    if isinstance(geom, LineString):
        yield geom
    elif isinstance(geom, MultiLineString):
        for g in geom.geoms:
            yield from _segments(g)


def _topology_qa(links: gpd.GeoDataFrame, nodes: gpd.GeoDataFrame) -> dict:
    phys = links[~links["e_id"].astype(str).str.endswith("_r")]
    adj: dict[int, set[int]] = defaultdict(set)
    for _, r in phys.iterrows():
        u, v = int(r["from_id"]), int(r["to_id"])
        adj[u].add(v)
        adj[v].add(u)
    seen: set[int] = set()
    components: list[int] = []
    for start in adj:
        if start in seen:
            continue
        stack = [start]
        seen.add(start)
        size = 0
        while stack:
            u = stack.pop()
            size += 1
            for w in adj[u]:
                if w not in seen:
                    seen.add(w)
                    stack.append(w)
        components.append(size)
    components.sort(reverse=True)
    deg_vals = np.array([len(adj[n]) for n in adj], dtype=int) if adj else np.array([0])
    n_nodes = len(nodes)
    largest = int(components[0]) if components else 0
    n_junction = int((deg_vals >= 3).sum()) if len(deg_vals) else 0
    tier_counts = {
        str(k): int(v)
        for k, v in phys["assignment_tier"].value_counts(dropna=False).items()
    }
    return {
        "n_directed_edges": int(len(links)),
        "n_physical_edges": int(len(phys)),
        "n_nodes": int(n_nodes),
        "n_components": int(len(components)),
        "largest_component_frac_nodes": float(largest / n_nodes) if n_nodes else 0.0,
        "top5_component_sizes": [int(x) for x in components[:5]],
        "n_junction_nodes_deg_ge3": n_junction,
        "junction_frac_nodes": float(n_junction / n_nodes) if n_nodes else 0.0,
        "degree_histogram": {
            str(k): int(v)
            for k, v in pd.Series(deg_vals).value_counts().sort_index().items()
        },
        "tier_counts_physical": tier_counts,
    }


def main() -> int:
    src = gpd.read_parquet(ART / "hpms_la_links.parquet")
    phys = src[~src["e_id"].astype(str).str.endswith("_r")].reset_index(drop=True)
    print(f"parents: {len(phys)}", flush=True)

    parent_geoms = [force_2d(g) for g in phys.geometry]
    tree = STRtree(parent_geoms)

    from shapely.ops import unary_union

    print("unary_union...", flush=True)
    noded = unary_union(parent_geoms)
    segs = [g for g in _segments(noded) if g is not None and g.length > 0]
    print(f"noded segments: {len(segs)}", flush=True)

    inv = 1.0 / SNAP_M
    node_key_to_id: dict[tuple[int, int], int] = {}
    next_id = NODE_ID_BASE

    def node_for(xy: tuple[float, float]) -> int:
        nonlocal next_id
        key = (int(round(xy[0] * inv)), int(round(xy[1] * inv)))
        if key not in node_key_to_id:
            node_key_to_id[key] = next_id
            next_id += 1
        return node_key_to_id[key]

    rows = []
    unmatched = 0
    for i, geom in enumerate(segs):
        mid = geom.interpolate(0.5, normalized=True)
        # nearest parent by distance; refuse if > 2m (should be ~0 for true children)
        idxs = tree.query(mid.buffer(2.0))
        if len(idxs) == 0:
            unmatched += 1
            continue
        best_i = None
        best_d = float("inf")
        for j in idxs:
            d = parent_geoms[int(j)].distance(mid)
            if d < best_d:
                best_d = d
                best_i = int(j)
        if best_i is None or best_d > 2.0:
            unmatched += 1
            continue
        parent = phys.iloc[best_i]
        coords = list(geom.coords)
        a = node_for((float(coords[0][0]), float(coords[0][1])))
        b = node_for((float(coords[-1][0]), float(coords[-1][1])))
        if a == b:
            continue
        e_id = f"{EDGE_ID_PREFIX}{i}"
        base = {c: parent[c] for c in _ATTR_COLS}
        base.update(
            {
                "e_id": e_id,
                "from_id": a,
                "to_id": b,
                "geometry": geom,
                "length": float(geom.length),
                "parent_e_id": parent["e_id"],
            }
        )
        rows.append(base)
        if not bool(parent["oneway"]):
            rev = dict(base)
            rev["e_id"] = f"{e_id}_r"
            rev["from_id"], rev["to_id"] = b, a
            rev["geometry"] = LineString(list(geom.coords)[::-1])
            rows.append(rev)

    if unmatched:
        print(f"unmatched segments dropped: {unmatched}")
    if not rows:
        raise ValueError("no attributed segments produced")

    links = gpd.GeoDataFrame(rows, crs=NETWORK_CRS)
    # Re-derive tier from hpms_fclass (parent copy should already be correct)
    links["assignment_tier"] = assignment_tier_from_fclass(
        pd.to_numeric(links["hpms_fclass"], errors="coerce").astype("Int64")
    )
    nodes = gpd.GeoDataFrame(
        [
            {"node_id": nid, "geometry": Point(qx * SNAP_M, qy * SNAP_M)}
            for (qx, qy), nid in node_key_to_id.items()
        ],
        crs=NETWORK_CRS,
    )
    qa = _topology_qa(links, nodes)
    qa["unmatched_segments"] = int(unmatched)
    print(json.dumps(qa, indent=2))

    links.to_parquet(ART / "hpms_la_links_noded.parquet")
    nodes.to_parquet(ART / "hpms_la_nodes_noded.parquet")
    (ART / "topology_qa_noded.json").write_text(json.dumps(qa, indent=2))
    print("wrote attributed noded artifacts")

    if qa["junction_frac_nodes"] < 0.05:
        print("GATE: STOP — junctions still too sparse after attributed noding")
        return 2
    print("GATE: attributed mid-noded graph clears junction bar — next: FAF5 splice on Hopper")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
