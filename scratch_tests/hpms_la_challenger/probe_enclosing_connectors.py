"""Dry-run connectors on mid-noded HPMS-LA with one-connector-per-segment rules.

Uses find_enclosing_connectors / is_eligible_attachment_edge from
network_connector_insertion.py, then enforces:
  - eligible only (no freeway / ramp / bridge / tunnel)
  - mid-segment attachment (library already uses fraction=0.5)
  - at most one connector per parent_e_id (pre-noding physical segment)
  - reject candidates whose attachment is within CORRIDOR_DEDUP_M of an
    already-chosen point (stops mid-noded corridor fragments looking like
    distinct roads — the Home #4 failure mode)

Primary output = uncapped enclosing-block rule after dedupe.
Also reports a target_k=4 attempt after the same dedupe (may return <4).
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point
from shapely.ops import polygonize

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "src"))

from resiflow.preprocess.network_connector_insertion import (  # noqa: E402
    find_enclosing_connectors,
    is_eligible_attachment_edge,
)

ART = Path(__file__).resolve().parent / "artifacts"
CENTROIDS = Path(__file__).resolve().parent / "la_centroids.json"
NETWORK_CRS = "EPSG:9311"
SEARCH_R = 3000.0
MAX_FACE = 300_000.0
CORRIDOR_DEDUP_M = 50.0  # attachment points closer than this => same corridor


def _flat(geom):
    while hasattr(geom, "geoms"):
        geom = geom.geoms[0]
    return geom


def _segment_key(row: pd.Series, e_id: str) -> str:
    """Stable 'one road' key: HPMS route_id when present, else parent_e_id."""
    rid = row.get("route_id")
    if rid is not None and not (isinstance(rid, float) and pd.isna(rid)):
        s = str(rid).strip()
        if s and s.lower() not in ("nan", "none"):
            return f"route:{s}"
    parent = row.get("parent_e_id")
    if parent is not None and not (isinstance(parent, float) and pd.isna(parent)):
        return f"parent:{parent}"
    return f"eid:{e_id}"


def _dedupe_connectors(atts: list[dict], links: gpd.GeoDataFrame) -> list[dict]:
    """Keep order; ≤1 connector per HPMS route_id (or parent segment) / corridor."""
    kept: list[dict] = []
    seen_keys: set[str] = set()
    for a in atts:
        row = links[links["e_id"].astype(str) == str(a["e_id"])]
        if row.empty:
            continue
        row = row.iloc[0]
        if not is_eligible_attachment_edge(row):
            continue
        key = _segment_key(row, str(a["e_id"]))
        if key in seen_keys:
            continue
        ax, ay = float(a["point"][0]), float(a["point"][1])
        if any(
            math.hypot(ax - float(k["point"][0]), ay - float(k["point"][1])) < CORRIDOR_DEDUP_M
            for k in kept
        ):
            continue
        seen_keys.add(key)
        enriched = dict(a)
        enriched["parent_e_id"] = str(row.get("parent_e_id") or a["e_id"])
        enriched["route_id"] = None if pd.isna(row.get("route_id")) else str(row.get("route_id"))
        enriched["segment_key"] = key
        kept.append(enriched)
    return kept


def _enrich(atts: list[dict], links: gpd.GeoDataFrame, centroid_pt: Point) -> list[dict]:
    out = []
    for a in atts:
        row = links[links["e_id"].astype(str) == str(a["e_id"])].iloc[0]
        att_pt = (
            gpd.GeoSeries([Point(a["point"][0], a["point"][1])], crs=NETWORK_CRS)
            .to_crs(4326)
            .iloc[0]
        )
        name = row.get("Road_Name")
        if name is not None and isinstance(name, float) and pd.isna(name):
            name = None
        elif name is not None:
            name = str(name).strip() or None
        out.append(
            {
                "e_id": str(a["e_id"]),
                "parent_e_id": str(a.get("parent_e_id") or row.get("parent_e_id") or a["e_id"]),
                "route_id": a.get("route_id")
                if a.get("route_id") is not None
                else (None if pd.isna(row.get("route_id")) else str(row.get("route_id"))),
                "segment_key": a.get("segment_key") or _segment_key(row, str(a["e_id"])),
                "fraction": a["fraction"],
                "length_m": float(centroid_pt.distance(Point(a["point"]))),
                "mid_lonlat": [att_pt.x, att_pt.y],
                "road_name": name,
                "tier": None if pd.isna(row.get("assignment_tier")) else str(row.get("assignment_tier")),
                "hpms_fclass": int(row["hpms_fclass"]) if pd.notna(row.get("hpms_fclass")) else None,
                "road_bridge": row.get("road_bridge"),
                "road_tunnel": row.get("road_tunnel"),
            }
        )
    return out


def diagnose_one(endpoint: str, c: dict, links: gpd.GeoDataFrame) -> dict:
    pt = gpd.GeoSeries([Point(c["lon"], c["lat"])], crs="EPSG:4326").to_crs(NETWORK_CRS).iloc[0]
    cx, cy = float(pt.x), float(pt.y)
    centroid_pt = Point(cx, cy)

    bbox = (cx - SEARCH_R, cy - SEARCH_R, cx + SEARCH_R, cy + SEARCH_R)
    local = links.cx[bbox[0]:bbox[2], bbox[1]:bbox[3]]
    eligible = local[local.apply(is_eligible_attachment_edge, axis=1)]
    n_local = int(len(local))
    n_elig = int(len(eligible))

    faces = list(polygonize([_flat(g) for g in eligible.geometry]))
    enclosing = next(
        (f for f in faces if f.area <= MAX_FACE and f.contains(centroid_pt)),
        None,
    )
    too_big = [float(f.area) for f in faces if f.contains(centroid_pt) and f.area > MAX_FACE]

    raw_uncapped = find_enclosing_connectors(
        cx, cy, links, target_k=None, search_radius_m=SEARCH_R, max_face_area_m2=MAX_FACE
    )
    raw_k4 = find_enclosing_connectors(
        cx, cy, links, target_k=4, search_radius_m=SEARCH_R, max_face_area_m2=MAX_FACE
    )
    # Pull a wider candidate pool for honest 2–4 fill after corridor dedupe:
    # take up to 12 nearest eligible midpoints, then dedupe, then keep ≤4.
    raw_pool = find_enclosing_connectors(
        cx, cy, links, target_k=12, search_radius_m=SEARCH_R, max_face_area_m2=MAX_FACE
    )

    uncapped = _dedupe_connectors(raw_uncapped, links)
    k4_raw_deduped = _dedupe_connectors(raw_k4, links)
    pool_deduped = _dedupe_connectors(raw_pool, links)
    # Prefer enclosing-block sides first (uncapped order), then pad from pool
    chosen_for_2_4: list[dict] = []
    seen = set()
    for a in uncapped + pool_deduped:
        key = a.get("segment_key") or a.get("parent_e_id") or a["e_id"]
        if key in seen:
            continue
        ax, ay = float(a["point"][0]), float(a["point"][1])
        if any(
            math.hypot(ax - float(k["point"][0]), ay - float(k["point"][1])) < CORRIDOR_DEDUP_M
            for k in chosen_for_2_4
        ):
            continue
        seen.add(key)
        chosen_for_2_4.append(a)
        if len(chosen_for_2_4) >= 4:
            break

    uncapped_e = _enrich(uncapped, links, centroid_pt)
    k4_e = _enrich(k4_raw_deduped[:4], links, centroid_pt)
    connectors_2_4 = _enrich(chosen_for_2_4, links, centroid_pt)
    n = len(connectors_2_4)

    reasons = []
    if n_elig == 0:
        reasons.append(
            f"No eligible edges within {SEARCH_R:.0f}m (local={n_local}). "
            "Eligibility excludes freeway, ramp, bridge, tunnel."
        )
    elif enclosing is None:
        reasons.append(
            "Centroid NOT inside a polygonized eligible-road block face ≤ "
            f"{MAX_FACE:,.0f} m² — uncapped rule returns nearest eligible edge only."
        )
        if too_big:
            reasons.append(
                f"Containing face exists but area={max(too_big):,.0f} m² exceeds "
                f"max_face_area_m2={MAX_FACE:,.0f} (superblock → treated as unenclosed)."
            )
    else:
        reasons.append(
            f"Enclosed face area={enclosing.area:,.0f} m²; "
            f"{len(uncapped_e)} unique-segment connector(s) on the boundary after dedupe."
        )

    n_dropped_corridor = max(0, len(raw_k4) - len(k4_raw_deduped))
    if n_dropped_corridor:
        reasons.append(
            f"Corridor/parent dedupe removed {n_dropped_corridor} of {len(raw_k4)} "
            f"raw target_k=4 candidates (same parent_e_id or <{CORRIDOR_DEDUP_M:.0f}m apart)."
        )
    if n < 2:
        reasons.append(
            f"After unique-segment rules only {n} connector(s) remain "
            f"(eligible nearby={n_elig}); cannot invent attachments."
        )
    elif n < 4:
        reasons.append(f"Have {n} unique-segment connectors (in/near 2–4 band, shy of 4).")
    else:
        reasons.append(f"Have {n} unique-segment connectors (hits the 2–4 target).")

    return {
        "endpoint": endpoint,
        "subarea_rank": c["subarea_rank"],
        "faf5_node_id": c["faf5_node_id"],
        "weight": c["weight"],
        "centroid_lonlat": [c["lon"], c["lat"]],
        "n_local_edges_3km": n_local,
        "n_eligible_edges_3km": n_elig,
        "enclosed": enclosing is not None,
        "enclosing_face_area_m2": float(enclosing.area) if enclosing is not None else None,
        "containing_oversized_face_areas_m2": too_big,
        "num_connectors_uncapped": len(uncapped_e),
        "num_connectors_target_k4_raw_deduped": len(k4_e),
        "num_connectors_unique_segment": n,
        "connectors_uncapped": uncapped_e,
        "connectors_unique_segment": connectors_2_4,  # map these
        "short_of_2_to_4": n < 2 or n > 4,
        "reasons": reasons,
        "rules": {
            "max_per_route_id": 1,
            "max_per_parent_e_id": 1,
            "corridor_dedup_m": CORRIDOR_DEDUP_M,
            "eligibility": "is_eligible_attachment_edge (no freeway/ramp/bridge/tunnel)",
            "fraction": 0.5,
        },
    }


def main() -> int:
    links = gpd.read_parquet(ART / "hpms_la_links_noded.parquet")
    phys = links[~links["e_id"].astype(str).str.endswith("_r")].copy()
    cents = json.loads(CENTROIDS.read_text())
    rows = []
    for endpoint in ("work", "home"):
        for c in cents[endpoint]:
            print(f"probing {endpoint} rank {c['subarea_rank']}...", flush=True)
            rows.append(diagnose_one(endpoint, c, phys))

    out = {
        "network": "hpms_la_links_noded (arterial/freeway/collector; locals excluded)",
        "search_radius_m": SEARCH_R,
        "max_face_area_m2": MAX_FACE,
        "corridor_dedup_m": CORRIDOR_DEDUP_M,
        "rows": rows,
    }
    path = ART / "enclosing_connector_probe.json"
    path.write_text(json.dumps(out, indent=2, allow_nan=False))
    print(f"wrote {path}")
    for r in rows:
        print(
            f"{r['endpoint']} r{r['subarea_rank']}: uncapped={r['num_connectors_uncapped']} "
            f"unique={r['num_connectors_unique_segment']} enclosed={r['enclosed']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
