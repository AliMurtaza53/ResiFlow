"""Build a noded, LA-County-only HPMS graph (challenger arm, session 1).

Mandate: FIPS 06037 only. Fixed budget. Topology QA is the stop/advance gate
before any FAF5 splice or assignment run. Reuses
``resiflow.hpms_fclass.assignment_tier_from_fclass`` — does not re-derive tiers.

Outputs under --out-dir:
  hpms_la_links.parquet / hpms_la_nodes.parquet
  topology_qa.json

ponytail: endpoint snap only (1 m in EPSG:9311). Mid-segment crossing noding
deferred; if largest-component coverage is too weak, STOP per mandate — do not
invent a national noding pipeline.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
from shapely.geometry import LineString, MultiLineString, Point

# Repo root = parents[2] of this file (scratch_tests/hpms_la_challenger/..)
_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from resiflow.hpms_fclass import assignment_tier_from_fclass  # noqa: E402

LA_FIPS = "06037"
LA_COUNTY_ID = 37  # HPMS county_id within CA
HPMS_DEFAULT = "/vsizip/C:/Users/akothaw/Desktop/data/faf5_data/HPMS2024.zip/HPMS2024.gdb"
LAYER = "HPMS_FULL_CA_2024"
COUNTY_SHP = Path(r"C:/Users/akothaw/Desktop/data/faf5_data/county_shp/tl_2022_us_county.shp")
NETWORK_CRS = "EPSG:9311"  # same as faf5_road_links.gpq on Hopper
NODE_ID_BASE = 500_000  # clear of FAF5 0..344998 and connector 345000+/410000+
EDGE_ID_PREFIX = "hpms_"

# Columns read from HPMS (keep narrow — full CA layer is huge)
_HPMS_COLS = [
    "route_id",
    "begin_point",
    "end_point",
    "f_system",
    "through_lanes",
    "speed_limit",
    "structure_type",
    "facility_type",
    "nhs",
    "county_id",
    "urban_id",
    "access_control",
    "routename",
]


def _as_linestring(geom) -> LineString | None:
    if geom is None or geom.is_empty:
        return None
    if isinstance(geom, LineString):
        return geom
    if isinstance(geom, MultiLineString):
        # LRS sections are almost always single-part; take longest part rather
        # than inventing a merge across gaps.
        parts = list(geom.geoms)
        if not parts:
            return None
        return max(parts, key=lambda g: g.length)
    return None


def _endpoints(geom: LineString) -> tuple[tuple[float, float], tuple[float, float]]:
    coords = list(geom.coords)
    return (float(coords[0][0]), float(coords[0][1])), (
        float(coords[-1][0]),
        float(coords[-1][1]),
    )


def load_la_county_polygon() -> gpd.GeoDataFrame:
    la = pyogrio.read_dataframe(
        COUNTY_SHP, where=f"GEOID='{LA_FIPS}'", columns=["GEOID", "NAME"]
    )
    if len(la) != 1:
        raise ValueError(f"expected 1 LA County row for GEOID={LA_FIPS}, got {len(la)}")
    return la


def load_hpms_la(hpms_path: str, la_poly_4326) -> gpd.GeoDataFrame:
    """Spatial clip to LA County polygon.

    Do NOT filter on HPMS ``county_id`` alone: in the 2024 CA Full Extent
    layer, f_system=7 (local) is almost entirely county_id=null, so an
    attribute filter silently drops the densification this challenger exists
    to test. Spatial intersect is the authoritative LA boundary.
    """
    bbox = tuple(la_poly_4326.total_bounds)
    raw = pyogrio.read_dataframe(hpms_path, layer=LAYER, bbox=bbox, columns=_HPMS_COLS)
    if raw.crs is None:
        raise ValueError("HPMS layer has no CRS")
    la_geom = la_poly_4326.to_crs(raw.crs).geometry.iloc[0]
    raw = raw[raw.intersects(la_geom)].copy()
    if raw.empty:
        raise ValueError("no HPMS features after LA County clip — check path/layer")
    return raw


def build_noded_graph(hpms: gpd.GeoDataFrame, snap_m: float = 1.0) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, dict]:
    """Endpoint-snap noding in NETWORK_CRS. Returns links, nodes, qa dict."""
    g = hpms.to_crs(NETWORK_CRS).copy()
    # Quantize to snap_m grid for endpoint identity
    inv = 1.0 / snap_m
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
    skipped = 0
    for i, row in g.iterrows():
        geom = _as_linestring(row.geometry)
        if geom is None or geom.length <= 0:
            skipped += 1
            continue
        a_xy, b_xy = _endpoints(geom)
        from_id = node_for(a_xy)
        to_id = node_for(b_xy)
        if from_id == to_id:
            skipped += 1
            continue

        f_sys = pd.to_numeric(row.get("f_system"), errors="coerce")
        if pd.isna(f_sys) or int(f_sys) not in (1, 2, 3, 4, 5, 6, 7):
            # no silent fallback — leave unclassified; downstream may drop
            hpms_fclass = pd.NA
            tier = pd.NA
        else:
            hpms_fclass = int(f_sys)
            tier = assignment_tier_from_fclass(pd.Series([hpms_fclass])).iloc[0]

        lanes = pd.to_numeric(row.get("through_lanes"), errors="coerce")
        if pd.isna(lanes) or lanes <= 0:
            raise ValueError(
                f"HPMS row route_id={row.get('route_id')!r} begin={row.get('begin_point')!r} "
                f"missing/invalid through_lanes={row.get('through_lanes')!r}; refuse to invent lanes"
            )
        speed = pd.to_numeric(row.get("speed_limit"), errors="coerce")
        # speed_limit is often null on locals; assignment falls back to tier profile
        # when Speed_Limit/AB_FinalSpeed absent — leave null, do not invent mph.

        struct = pd.to_numeric(row.get("structure_type"), errors="coerce")
        # HPMS: 1=bridge, 2=tunnel (field manual); others = at-grade
        road_bridge = "yes" if struct == 1 else "no"
        road_tunnel = "yes" if struct == 2 else "no"
        if struct == 1:
            road_label = "bridge"
        elif struct == 2:
            road_label = "tunnel"
        else:
            road_label = "road"

        facility = pd.to_numeric(row.get("facility_type"), errors="coerce")
        # 1 = one-way roadway in HPMS field manual; 2 = two-way
        oneway = True if facility == 1 else False

        e_id = f"{EDGE_ID_PREFIX}{i}"
        base = {
            "e_id": e_id,
            "from_id": from_id,
            "to_id": to_id,
            "geometry": geom,
            "length": float(geom.length),
            "network_source": "hpms_la",
            "hpms_fclass": hpms_fclass,
            "assignment_tier": tier,
            "lanes": int(lanes),
            "Speed_Limit": float(speed) if pd.notna(speed) else pd.NA,
            "nhs_designation": pd.to_numeric(row.get("nhs"), errors="coerce"),
            "road_bridge": road_bridge,
            "road_tunnel": road_tunnel,
            "road_label": road_label,
            "bridge_fraction": 1.0 if road_bridge == "yes" else 0.0,
            "tunnel_fraction": 1.0 if road_tunnel == "yes" else 0.0,
            "Road_Name": row.get("routename"),
            "route_id": row.get("route_id"),
            "begin_point": row.get("begin_point"),
            "end_point": row.get("end_point"),
            "faf5_class": pd.NA,
            "oneway": oneway,
            "County_Name": "Los Angeles",
            "STATE": "CA",
        }
        rows.append(base)
        if not oneway:
            # reverse twin with distinct e_id (FAF5 stores directed rows)
            rev = dict(base)
            rev["e_id"] = f"{e_id}_r"
            rev["from_id"], rev["to_id"] = to_id, from_id
            rev["geometry"] = LineString(list(geom.coords)[::-1])
            rows.append(rev)

    if not rows:
        raise ValueError("no edges survived noding")

    links = gpd.GeoDataFrame(rows, crs=NETWORK_CRS)
    # Materialize node points at snap-grid centers
    node_rows = []
    for (qx, qy), nid in node_key_to_id.items():
        node_rows.append(
            {"node_id": nid, "geometry": Point(qx * snap_m, qy * snap_m)}
        )
    nodes = gpd.GeoDataFrame(node_rows, crs=NETWORK_CRS)

    qa = topology_qa(links, nodes, skipped_geoms=skipped, snap_m=snap_m)
    return links, nodes, qa


def topology_qa(links: gpd.GeoDataFrame, nodes: gpd.GeoDataFrame, *, skipped_geoms: int, snap_m: float) -> dict:
    """Connected-component + degree stats — the stop/advance signal."""
    # undirected components over unique physical edges (drop _r twins)
    phys = links[~links["e_id"].astype(str).str.endswith("_r")].copy()
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
            for v in adj[u]:
                if v not in seen:
                    seen.add(v)
                    stack.append(v)
        components.append(size)
    components.sort(reverse=True)

    degrees = {n: len(adj[n]) for n in adj}
    deg_vals = np.array(list(degrees.values()), dtype=int) if degrees else np.array([0])

    tier_counts = (
        phys["assignment_tier"].value_counts(dropna=False).astype(int).to_dict()
    )
    # stringify NA key for JSON
    tier_counts = {str(k): int(v) for k, v in tier_counts.items()}

    n_nodes = len(nodes)
    largest = int(components[0]) if components else 0
    n_junction = int((deg_vals >= 3).sum()) if len(deg_vals) else 0
    qa = {
        "snap_m": snap_m,
        "n_directed_edges": int(len(links)),
        "n_physical_edges": int(len(phys)),
        "n_nodes": int(n_nodes),
        "skipped_geoms": int(skipped_geoms),
        "n_components": int(len(components)),
        "largest_component_nodes": largest,
        "largest_component_frac_nodes": float(largest / n_nodes) if n_nodes else 0.0,
        "top5_component_sizes": [int(x) for x in components[:5]],
        # Real intersection signal: LRS chains are mostly deg=2; a routable
        # urban grid needs abundant deg>=3 nodes. Largest-component fraction
        # alone can look healthy on a long polyline soup.
        "n_junction_nodes_deg_ge3": n_junction,
        "junction_frac_nodes": float(n_junction / n_nodes) if n_nodes else 0.0,
        "degree_histogram": {
            str(k): int(v)
            for k, v in pd.Series(deg_vals).value_counts().sort_index().items()
        },
        "tier_counts_physical": tier_counts,
        "n_missing_tier": int(phys["assignment_tier"].isna().sum()),
        "n_bridge": int((phys["road_bridge"] == "yes").sum()),
        "n_tunnel": int((phys["road_tunnel"] == "yes").sum()),
        "n_oneway_facility": int(phys["oneway"].sum()),
    }
    return qa


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hpms", default=HPMS_DEFAULT)
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "artifacts",
    )
    ap.add_argument("--snap-m", type=float, default=1.0)
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    print("Loading LA County polygon...", flush=True)
    la = load_la_county_polygon()
    print("Reading + clipping HPMS CA -> LA County...", flush=True)
    hpms = load_hpms_la(args.hpms, la)
    print(f"  clipped features: {len(hpms)}", flush=True)

    # through_lanes nulls: report and drop rather than invent
    lanes = pd.to_numeric(hpms["through_lanes"], errors="coerce")
    bad = lanes.isna() | (lanes <= 0)
    if bad.any():
        print(f"  dropping {int(bad.sum())} features with missing/invalid through_lanes")
        hpms = hpms.loc[~bad].copy()
        if hpms.empty:
            raise ValueError("all features lacked through_lanes")

    print(f"Noding at snap={args.snap_m}m in {NETWORK_CRS}...", flush=True)
    links, nodes, qa = build_noded_graph(hpms, snap_m=args.snap_m)
    print(json.dumps(qa, indent=2))

    links_path = args.out_dir / "hpms_la_links.parquet"
    nodes_path = args.out_dir / "hpms_la_nodes.parquet"
    qa_path = args.out_dir / "topology_qa.json"
    links.to_parquet(links_path)
    nodes.to_parquet(nodes_path)
    qa_path.write_text(json.dumps(qa, indent=2))
    print(f"wrote {links_path}")
    print(f"wrote {nodes_path}")
    print(f"wrote {qa_path}")

    # Stop/advance hint (not a hard assert — user confirms the real bar).
    # Junction fraction is the binding signal; component fraction is secondary.
    frac = qa["largest_component_frac_nodes"]
    jfrac = qa["junction_frac_nodes"]
    if jfrac < 0.05 or frac < 0.5:
        print(
            f"\nGATE: STOP candidate — largest component {frac:.1%} of nodes, "
            f"junctions (deg>=3) only {jfrac:.1%} ({qa['n_junction_nodes_deg_ge3']} nodes). "
            "Endpoint snap is not producing a routable urban grid; mid-segment "
            "noding would be required before any fair assignment comparison."
        )
        return 2
    print(
        f"\nGATE: largest component {frac:.1%}, junctions {jfrac:.1%} — "
        "topology plausible enough to design FAF5 splice."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
