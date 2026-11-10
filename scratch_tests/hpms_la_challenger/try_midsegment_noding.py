"""Bounded mid-segment noding trial on the already-built lane-valid LA HPMS edges.

Uses GEOS unary_union to insert vertices at pairwise line intersections, then
re-explodes to segments and re-runs the same topology QA. If junction fraction
stays <<5%, the challenger stops — do not escalate to a custom noding pipeline.

ponytail: attributes are NOT transferred through unary_union (geometry-only
trial). A production splice would need attribute recovery; this script only
answers 'does planar noding create a grid?'
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely import force_2d
from shapely.geometry import LineString, MultiLineString, Point
from shapely.ops import unary_union

ART = Path(__file__).resolve().parent / "artifacts"
NETWORK_CRS = "EPSG:9311"
SNAP_M = 1.0


def _segments(geom):
    if geom is None or geom.is_empty:
        return
    if isinstance(geom, LineString):
        yield geom
    elif isinstance(geom, MultiLineString):
        for g in geom.geoms:
            yield from _segments(g)


def topology_qa_from_lines(lines: list[LineString]) -> dict:
    inv = 1.0 / SNAP_M
    node_key_to_id: dict[tuple[int, int], int] = {}
    next_id = 0

    def node_for(xy):
        nonlocal next_id
        key = (int(round(xy[0] * inv)), int(round(xy[1] * inv)))
        if key not in node_key_to_id:
            node_key_to_id[key] = next_id
            next_id += 1
        return node_key_to_id[key]

    edges = []
    for geom in lines:
        if geom.length <= 0:
            continue
        coords = list(geom.coords)
        a = node_for((float(coords[0][0]), float(coords[0][1])))
        b = node_for((float(coords[-1][0]), float(coords[-1][1])))
        if a == b:
            continue
        edges.append((a, b))

    adj: dict[int, set[int]] = defaultdict(set)
    for u, v in edges:
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
            for v in adj[u]:
                if v not in seen:
                    seen.add(v)
                    stack.append(v)
        components.append(size)
    components.sort(reverse=True)

    deg_vals = np.array([len(adj[n]) for n in adj], dtype=int) if adj else np.array([0])
    n_nodes = len(node_key_to_id)
    largest = int(components[0]) if components else 0
    n_junction = int((deg_vals >= 3).sum())
    return {
        "n_physical_edges": len(edges),
        "n_nodes": n_nodes,
        "n_components": len(components),
        "largest_component_frac_nodes": float(largest / n_nodes) if n_nodes else 0.0,
        "top5_component_sizes": [int(x) for x in components[:5]],
        "n_junction_nodes_deg_ge3": n_junction,
        "junction_frac_nodes": float(n_junction / n_nodes) if n_nodes else 0.0,
        "degree_histogram": {
            str(k): int(v)
            for k, v in pd.Series(deg_vals).value_counts().sort_index().items()
        },
    }


def main() -> int:
    links = gpd.read_parquet(ART / "hpms_la_links.parquet")
    phys = links[~links["e_id"].astype(str).str.endswith("_r")].copy()
    print(f"input physical edges: {len(phys)}", flush=True)

    # Geometry-only planar noding
    geoms = [force_2d(g) for g in phys.geometry if g is not None and not g.is_empty]
    print(f"unary_union over {len(geoms)} geometries...", flush=True)
    noded = unary_union(geoms)
    print(f"  result type={noded.geom_type}", flush=True)
    segs = [g for g in _segments(noded) if g.length > 0]
    print(f"  exploded segments: {len(segs)}", flush=True)

    qa = topology_qa_from_lines(segs)
    print(json.dumps(qa, indent=2))
    out = ART / "topology_qa_midsegment.json"
    out.write_text(json.dumps(qa, indent=2))
    print(f"wrote {out}")

    jfrac = qa["junction_frac_nodes"]
    if jfrac < 0.05:
        print(
            f"\nGATE: STOP — mid-segment unary_union still only {jfrac:.1%} junctions. "
            "HPMS-LA is not a cheap densification win."
        )
        return 2
    print(f"\nGATE: mid-segment noding raised junctions to {jfrac:.1%} — continue.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
