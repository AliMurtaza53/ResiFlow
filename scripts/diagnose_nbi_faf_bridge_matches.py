#!/usr/bin/env python3
"""QA diagnostics for NBI→FAF bridge proximity matches.

The production join (`build_nbi_bridge_index.py`) is nearest-link within
100 m — it does not gate on facility type. This script re-runs that join
at structure level and reports:

1. NBI functional class vs FAF class / road_classification (coarse-tier jump)
2. FACILITY_CARRIED vs FAF Road_Name token / route-number overlap
3. Ramp flag vs motorway_link (existing diagnostic, quantified)
4. Second-nearest competitor within 100 m for class-jump / name-miss suspects
   (overpass / missing-facility pattern): whether a farther FAF link agrees
   better on class or name

Absolute structure bearing is not in NBI; "parallel" is approximated by
comparing nearest vs competitor link bearings when both exist (near-
perpendicular pair ≈ crossing / overpass geometry).

Usage::

    python scripts/diagnose_nbi_faf_bridge_matches.py \\
        --nbi .../nbi_bridges_ntad.parquet \\
        --road-links .../faf5_road_links.gpq \\
        --output-dir .../enrichment/bridge_match_qa
"""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point

TARGET_CRS = "EPSG:9311"
MAX_DIST_M = 100.0

# Coarse tiers for jump detection (order = hierarchy for "drop" measure).
NBI_TIER = {
    "Rural - Principal Arterial - Interstate": "interstate",
    "Urban - Principal Arterial - Interstate": "interstate",
    "Urban - Principal Arterial - Other Freeway/Expressway": "freeway",
    "Rural - Principal Arterial - Other": "principal_arterial",
    "Urban - Other Principal Arterial": "principal_arterial",
    "Rural - Minor Arterial": "minor_arterial",
    "Urban - Minor Arterial": "minor_arterial",
    "Rural - Major Collector": "collector",
    "Rural - Minor Collector": "collector",
    "Urban - Collector": "collector",
    "Rural - Local": "local",
    "Urban - Local": "local",
}
TIER_RANK = {
    "interstate": 5,
    "freeway": 5,
    "principal_arterial": 4,
    "minor_arterial": 3,
    "collector": 2,
    "local": 1,
    "ramp": 4,  # treat as high-system connector for jump size
    "service": 1,
    "other": 0,
    "unknown": -1,
}

FAF_CLASS_TIER = {
    11: "interstate",
    13: "interstate",
    33: "interstate",
    12: "freeway",
    14: "principal_arterial",  # FAF merges arterial + major collector
    15: "local",
    21: "ramp",
    22: "ramp",
    23: "freeway",  # C/D lanes
    16: "service",
    17: "service",
    18: "service",
    19: "service",
    36: "service",
    41: "other",
}

_STOP = frozenset(
    {
        "RAMP",
        "OVER",
        "UNDER",
        "ROAD",
        "RD",
        "STREET",
        "ST",
        "AVE",
        "AVENUE",
        "BLVD",
        "HWY",
        "HIGHWAY",
        "ROUTE",
        "RTE",
        "SR",
        "US",
        "IH",
        "I",
        "THE",
        "OF",
        "AND",
        "TO",
        "N",
        "S",
        "E",
        "W",
        "NB",
        "SB",
        "EB",
        "WB",
        "NORTH",
        "SOUTH",
        "EAST",
        "WEST",
        "BOUND",
        "CONNECTOR",
        "ACCESS",
        "FRONTAGE",
    }
)
_ROUTE_RE = re.compile(
    r"\b(?:I|IH|US|SR|SH|CA|NY|TX|FL|VA|MD|PA|OH|IL|GA|NC|SC|WA|OR|CO|AZ|NM)?[-\s]?"
    r"(\d{1,3}[A-Z]?)\b",
    re.I,
)


def faf_tier(faf5_class, road_classification: str | None) -> str:
    if pd.notna(faf5_class):
        t = FAF_CLASS_TIER.get(int(faf5_class))
        if t:
            return t
    rc = (road_classification or "").strip().lower()
    if rc in {"motorway", "motorway_link"}:
        return "interstate" if rc == "motorway" else "ramp"
    if rc == "trunk":
        return "freeway"
    if rc in {"primary", "secondary"}:
        return "principal_arterial"
    if rc in {"tertiary", "unclassified"}:
        return "collector"
    if rc == "service":
        return "service"
    return "unknown"


def nbi_tier(functional_class: str | None) -> str:
    if functional_class is None or (isinstance(functional_class, float) and math.isnan(functional_class)):
        return "unknown"
    return NBI_TIER.get(str(functional_class).strip(), "unknown")


def tier_jump(nbi: str, faf: str) -> int:
    """Absolute rank gap; -1 if either unknown."""
    a, b = TIER_RANK.get(nbi, -1), TIER_RANK.get(faf, -1)
    if a < 0 or b < 0:
        return -1
    return abs(a - b)


def name_tokens(text: str | None) -> set[str]:
    if text is None or (isinstance(text, float) and math.isnan(text)):
        return set()
    s = str(text).upper()
    s = re.sub(r"[^A-Z0-9\s\-]", " ", s)
    toks = set()
    for t in re.split(r"[\s\-]+", s):
        if not t or t in _STOP:
            continue
        if t.isdigit() and len(t) > 3:
            continue
        toks.add(t)
    return toks


def route_numbers(text: str | None) -> set[str]:
    if text is None or (isinstance(text, float) and math.isnan(text)):
        return set()
    return {m.group(1).upper() for m in _ROUTE_RE.finditer(str(text))}


def name_overlap(facility: str | None, road_name: str | None) -> dict:
    ft, rn = name_tokens(facility), name_tokens(road_name)
    fr, rr = route_numbers(facility), route_numbers(road_name)
    shared_tok = ft & rn
    shared_rte = fr & rr
    return {
        "shared_tokens": sorted(shared_tok),
        "shared_routes": sorted(shared_rte),
        "name_hit": bool(shared_tok or shared_rte),
        "n_shared_tokens": len(shared_tok),
        "n_shared_routes": len(shared_rte),
        "both_named": bool(ft) and bool(rn or rr),
    }


def link_bearing_deg(geom, point) -> float | None:
    """Bearing (degrees from north) of the link segment nearest to point."""
    if geom is None or point is None:
        return None
    try:
        if geom.is_empty:
            return None
    except Exception:
        return None
    # FAF links are often MultiLineString in the parquet
    try:
        from shapely.ops import linemerge

        if geom.geom_type == "MultiLineString":
            merged = linemerge(geom)
            geom = merged if merged.geom_type == "LineString" else max(geom.geoms, key=lambda g: g.length)
        if geom.geom_type != "LineString":
            return None
        coords = list(geom.coords)
    except Exception:
        return None
    if len(coords) < 2:
        return None
    best_i, best_d = 0, float("inf")
    px, py = point.x, point.y
    for i in range(len(coords) - 1):
        x0, y0 = coords[i][0], coords[i][1]
        x1, y1 = coords[i + 1][0], coords[i + 1][1]
        mx, my = 0.5 * (x0 + x1), 0.5 * (y0 + y1)
        d = (mx - px) ** 2 + (my - py) ** 2
        if d < best_d:
            best_d, best_i = d, i
    x0, y0 = coords[best_i][0], coords[best_i][1]
    x1, y1 = coords[best_i + 1][0], coords[best_i + 1][1]
    dx, dy = x1 - x0, y1 - y0
    if dx == 0 and dy == 0:
        return None
    return (math.degrees(math.atan2(dx, dy)) + 360.0) % 360.0


def bearing_delta_deg(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    d = abs(a - b) % 180.0
    return min(d, 180.0 - d)


def build_structure_matches(
    nbi: pd.DataFrame,
    links: gpd.GeoDataFrame,
    *,
    max_distance_m: float = MAX_DIST_M,
) -> gpd.GeoDataFrame:
    nbi_gdf = gpd.GeoDataFrame(
        nbi.copy(),
        geometry=[Point(lon, lat) for lon, lat in zip(nbi["longitude"], nbi["latitude"])],
        crs="EPSG:4326",
    ).to_crs(TARGET_CRS)

    keep = [
        "e_id",
        "geometry",
        "faf5_class",
        "road_classification",
        "road_classification_detail",
        "Road_Name",
        "length",
    ]
    missing = [c for c in ("e_id", "geometry") if c not in links.columns]
    if missing:
        raise KeyError(f"road_links missing required columns: {missing}")
    cols = [c for c in keep if c in links.columns]
    links_p = links[cols].to_crs(TARGET_CRS).copy()
    links_p["e_id"] = links_p["e_id"].astype(str)

    matched = gpd.sjoin_nearest(
        nbi_gdf,
        links_p,
        how="inner",
        max_distance=max_distance_m,
        distance_col="match_distance_m",
    )
    # One row per structure: keep closest (ties may duplicate e_ids at dist 0)
    matched = matched.sort_values("match_distance_m").drop_duplicates(
        subset=["structure_number"], keep="first"
    )
    return matched


def score_candidate(nbi_row, link_row) -> tuple[int, dict]:
    """Higher is better. Returns (score, detail)."""
    nt = nbi_tier(nbi_row.get("functional_class"))
    ft = faf_tier(link_row.get("faf5_class"), link_row.get("road_classification"))
    jump = tier_jump(nt, ft)
    nm = name_overlap(nbi_row.get("facility_carried"), link_row.get("Road_Name"))
    link_ramp = str(link_row.get("road_classification", "")).lower() == "motorway_link"
    ramp_ok = bool(nbi_row.get("is_ramp")) == link_ramp

    score = 0
    if nm["name_hit"]:
        score += 10
    if jump == 0:
        score += 5
    elif jump == 1:
        score += 2
    elif jump >= 3:
        score -= 5
    score += 2 if ramp_ok else -3
    return score, {
        "nbi_tier": nt,
        "faf_tier": ft,
        "tier_jump": jump,
        "name_hit": nm["name_hit"],
        "n_shared_tokens": nm["n_shared_tokens"],
        "n_shared_routes": nm["n_shared_routes"],
    }


def find_competitors(
    matched: gpd.GeoDataFrame,
    links_p: gpd.GeoDataFrame,
    *,
    max_distance_m: float = MAX_DIST_M,
    suspect_mask: pd.Series,
    max_suspects: int = 25000,
) -> pd.DataFrame:
    """For suspect structures, find any other FAF link within max_distance that scores better."""
    suspects = matched.loc[suspect_mask].head(max_suspects)
    if suspects.empty:
        return pd.DataFrame()

    tree = links_p.sindex
    link_geoms = links_p.geometry.values
    rows = []
    for _, r in suspects.iterrows():
        pt = r.geometry
        # candidate indices intersecting buffered point
        buf = pt.buffer(max_distance_m)
        idxs = list(tree.query(buf, predicate="intersects"))
        if not idxs:
            continue
        best_alt = None
        best_alt_score = -999
        best_alt_dist = None
        best_alt_bearing = None
        primary_score, _ = score_candidate(r, r)
        primary_bearing = link_bearing_deg(
            links_p.loc[links_p["e_id"] == str(r["e_id"]), "geometry"].iloc[0]
            if (links_p["e_id"] == str(r["e_id"])).any()
            else None,
            pt,
        )
        # use matched row's link geometry from join — may be in r if geometry is point
        # re-fetch link geom by e_id
        prim_geoms = links_p.loc[links_p["e_id"] == str(r["e_id"]), "geometry"]
        if len(prim_geoms):
            primary_bearing = link_bearing_deg(prim_geoms.iloc[0], pt)

        for i in idxs:
            link = links_p.iloc[i]
            if str(link["e_id"]) == str(r["e_id"]):
                continue
            dist = pt.distance(link.geometry)
            if dist > max_distance_m:
                continue
            sc, det = score_candidate(r, link)
            if sc > best_alt_score:
                best_alt_score = sc
                best_alt = (link, det, dist)
                best_alt_bearing = link_bearing_deg(link.geometry, pt)
                best_alt_dist = dist

        if best_alt is None:
            continue
        link, det, dist = best_alt
        better = best_alt_score > primary_score
        bdelta = bearing_delta_deg(primary_bearing, best_alt_bearing)
        rows.append(
            {
                "structure_number": r["structure_number"],
                "facility_carried": r.get("facility_carried"),
                "nbi_functional_class": r.get("functional_class"),
                "primary_e_id": r["e_id"],
                "primary_faf5_class": r.get("faf5_class"),
                "primary_road_name": r.get("Road_Name"),
                "primary_match_m": float(r["match_distance_m"]),
                "primary_score": primary_score,
                "alt_e_id": link["e_id"],
                "alt_faf5_class": link.get("faf5_class"),
                "alt_road_classification": link.get("road_classification"),
                "alt_road_name": link.get("Road_Name"),
                "alt_match_m": float(best_alt_dist),
                "alt_score": best_alt_score,
                "alt_better": better,
                "bearing_delta_deg": bdelta,
                "crossing_like": bdelta is not None and bdelta >= 60.0,
                "alt_nbi_tier": det["nbi_tier"],
                "alt_faf_tier": det["faf_tier"],
                "alt_tier_jump": det["tier_jump"],
                "alt_name_hit": det["name_hit"],
            }
        )
    return pd.DataFrame(rows)


def summarize(matched: gpd.GeoDataFrame, competitors: pd.DataFrame) -> dict:
    n = len(matched)
    matched = matched.copy()
    matched["nbi_tier"] = matched["functional_class"].map(nbi_tier)
    matched["faf_tier"] = [
        faf_tier(fc, rc)
        for fc, rc in zip(matched.get("faf5_class"), matched.get("road_classification"))
    ]
    matched["tier_jump"] = [tier_jump(a, b) for a, b in zip(matched["nbi_tier"], matched["faf_tier"])]
    nm = [name_overlap(f, r) for f, r in zip(matched["facility_carried"], matched.get("Road_Name"))]
    matched["name_hit"] = [x["name_hit"] for x in nm]
    matched["both_named"] = [x["both_named"] for x in nm]
    matched["n_shared_routes"] = [x["n_shared_routes"] for x in nm]

    link_is_ramp = matched["road_classification"].astype(str).str.lower().eq("motorway_link")
    matched["ramp_consistent"] = matched["is_ramp"].astype(bool) == link_is_ramp

    big_jump = matched["tier_jump"] >= 3
    mid_jump = matched["tier_jump"] == 2
    # NBI collector/local onto FAF interstate/freeway (classic under/overpass attach)
    underclass_on_freeway = matched["nbi_tier"].isin(["collector", "local"]) & matched[
        "faf_tier"
    ].isin(["interstate", "freeway", "ramp"])

    named = matched["both_named"]
    named_miss = named & ~matched["name_hit"]

    out = {
        "n_matched_structures": n,
        "match_distance_m": {
            "p50": float(matched["match_distance_m"].median()),
            "p90": float(matched["match_distance_m"].quantile(0.9)),
            "p95": float(matched["match_distance_m"].quantile(0.95)),
            "share_gt_25m": float((matched["match_distance_m"] > 25).mean()),
            "share_gt_50m": float((matched["match_distance_m"] > 50).mean()),
        },
        "ramp_consistency": {
            "agree_rate": float(matched["ramp_consistent"].mean()),
            "n_disagree": int((~matched["ramp_consistent"]).sum()),
        },
        "tier_agreement": {
            "jump0_same_tier": float((matched["tier_jump"] == 0).mean()),
            "jump1": float((matched["tier_jump"] == 1).mean()),
            "jump2": float((matched["tier_jump"] == 2).mean()),
            "jump_ge3": float(big_jump.mean()),
            "n_jump_ge3": int(big_jump.sum()),
            "n_underclass_on_freeway_or_ramp": int(underclass_on_freeway.sum()),
            "share_underclass_on_freeway_or_ramp": float(underclass_on_freeway.mean()),
        },
        "facility_name": {
            "n_both_named": int(named.sum()),
            "share_both_named": float(named.mean()),
            "hit_rate_among_both_named": float(matched.loc[named, "name_hit"].mean())
            if named.any()
            else None,
            "n_named_miss": int(named_miss.sum()),
            "route_number_hit_among_both_named": float(
                (matched.loc[named, "n_shared_routes"] > 0).mean()
            )
            if named.any()
            else None,
        },
        "nbi_tier_x_faf_tier": (
            matched.groupby(["nbi_tier", "faf_tier"], dropna=False)
            .size()
            .sort_values(ascending=False)
            .head(25)
            .rename("n")
            .reset_index()
            .to_dict(orient="records")
        ),
        "competitors": {
            "n_suspects_checked": int(len(competitors)) if competitors is not None and len(competitors) else 0,
            "n_with_better_alt": int(competitors["alt_better"].sum())
            if competitors is not None and len(competitors)
            else 0,
            "share_better_alt": float(competitors["alt_better"].mean())
            if competitors is not None and len(competitors)
            else None,
            "n_crossing_like_and_better_alt": int(
                (competitors["alt_better"] & competitors["crossing_like"]).sum()
            )
            if competitors is not None
            and len(competitors)
            and "crossing_like" in competitors.columns
            else 0,
        },
        "notes": [
            "Join is still proximity-only; these metrics diagnose false facility attachment.",
            "FAF class 14 merges arterial + major collector — some 'jumps' from NBI collector are soft.",
            "Road_Name is often blank or generic; name_hit rates only among rows with both names.",
            "Second-nearest competitor checked for tier_jump>=2, ramp disagree, or named miss.",
            "crossing_like = bearing delta between primary and alt link >= 60 deg (overpass proxy).",
        ],
    }
    return out, matched


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--nbi", type=Path, required=True)
    p.add_argument("--road-links", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--max-distance", type=float, default=MAX_DIST_M)
    p.add_argument("--max-suspects", type=int, default=25000)
    args = p.parse_args()

    nbi = pd.read_parquet(args.nbi)
    links = gpd.read_parquet(args.road_links)
    print(f"NBI structures: {len(nbi):,}  FAF links: {len(links):,}")

    matched = build_structure_matches(nbi, links, max_distance_m=args.max_distance)
    print(f"Matched structures within {args.max_distance} m: {len(matched):,}")

    # annotate for competitor filter
    tmp_nbi_tier = matched["functional_class"].map(nbi_tier)
    tmp_faf_tier = [
        faf_tier(fc, rc)
        for fc, rc in zip(matched.get("faf5_class"), matched.get("road_classification"))
    ]
    jumps = pd.Series([tier_jump(a, b) for a, b in zip(tmp_nbi_tier, tmp_faf_tier)], index=matched.index)
    link_is_ramp = matched["road_classification"].astype(str).str.lower().eq("motorway_link")
    ramp_bad = matched["is_ramp"].astype(bool) != link_is_ramp
    nm_miss = []
    for f, r in zip(matched["facility_carried"], matched.get("Road_Name")):
        o = name_overlap(f, r)
        nm_miss.append(o["both_named"] and not o["name_hit"])
    nm_miss = pd.Series(nm_miss, index=matched.index)
    suspect = (jumps >= 2) | ramp_bad | nm_miss

    links_p = links[
        [c for c in ("e_id", "geometry", "faf5_class", "road_classification", "Road_Name") if c in links.columns]
    ].to_crs(TARGET_CRS)
    links_p["e_id"] = links_p["e_id"].astype(str)

    print(f"Suspects for competitor search: {int(suspect.sum()):,} (cap {args.max_suspects})")
    competitors = find_competitors(
        matched,
        links_p,
        max_distance_m=args.max_distance,
        suspect_mask=suspect,
        max_suspects=args.max_suspects,
    )

    summary, annotated = summarize(matched, competitors)

    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    (out / "bridge_match_qa_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    sample_cols = [
        c
        for c in (
            "structure_number",
            "facility_carried",
            "functional_class",
            "is_ramp",
            "e_id",
            "faf5_class",
            "road_classification",
            "Road_Name",
            "match_distance_m",
            "nbi_tier",
            "faf_tier",
            "tier_jump",
            "name_hit",
            "ramp_consistent",
            "structure_length_m",
        )
        if c in annotated.columns
    ]
    flat = pd.DataFrame(annotated.drop(columns=["geometry"], errors="ignore"))

    flat.loc[flat["tier_jump"] >= 3].nlargest(500, "match_distance_m")[sample_cols].to_csv(
        out / "sample_tier_jump_ge3.csv", index=False
    )
    under = flat["nbi_tier"].isin(["collector", "local"]) & flat["faf_tier"].isin(
        ["interstate", "freeway", "ramp"]
    )
    flat.loc[under].nlargest(500, "match_distance_m")[sample_cols].to_csv(
        out / "sample_underclass_on_freeway.csv", index=False
    )
    flat.loc[~flat["ramp_consistent"]].nlargest(500, "match_distance_m")[sample_cols].to_csv(
        out / "sample_ramp_inconsistent.csv", index=False
    )
    if len(competitors):
        competitors.to_csv(out / "competitors_better_alt.csv", index=False)
        competitors.loc[competitors["alt_better"]].head(500).to_csv(
            out / "sample_better_competitor.csv", index=False
        )

    pd.crosstab(flat["nbi_tier"], flat["faf_tier"]).to_csv(out / "nbi_tier_x_faf_tier.csv")

    print(json.dumps(summary, indent=2))
    print(f"Wrote metrics + samples under {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
