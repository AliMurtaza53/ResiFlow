#!/usr/bin/env python3
"""Spatially join NTAD tunnel portals onto FAF5 road links.

Mirrors scripts/build_nbi_bridge_index.py: nearest FAF5 link within
--max-distance metres. Primary tunnel source for ResiFlow (HPMS
STRUCTURE_TYPE=2 on LRS-keyed links is QA-only).

Usage::

    python scripts/build_nti_tunnel_index.py \\
        --nti /path/to/nti_tunnels.parquet \\
        --road-links /path/to/faf5_road_links.gpq \\
        --output /path/to/faf5_tunnel_index.parquet \\
        --max-distance 100
"""

from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

TARGET_CRS = "EPSG:9311"


def build_tunnel_index(
    nti_path: Path,
    road_links_path: Path,
    *,
    max_distance_m: float = 100.0,
) -> tuple[pd.DataFrame, dict]:
    nti = pd.read_parquet(nti_path)
    if "tunnel_number" not in nti.columns:
        raise KeyError(f"{nti_path} missing required column 'tunnel_number'")
    for col in ("latitude", "longitude"):
        if col not in nti.columns:
            raise KeyError(f"{nti_path} missing required column {col!r}")

    road_links = gpd.read_parquet(road_links_path)
    if "e_id" not in road_links.columns:
        raise KeyError(f"{road_links_path} has no e_id column")
    if road_links.crs is None:
        raise ValueError(f"{road_links_path} has no CRS set -- cannot buffer-match in metres")

    nti_gdf = gpd.GeoDataFrame(
        nti,
        geometry=[Point(lon, lat) for lon, lat in zip(nti["longitude"], nti["latitude"])],
        crs="EPSG:4326",
    ).to_crs(TARGET_CRS)
    links_proj = road_links[["e_id", "geometry"]].to_crs(TARGET_CRS)

    matched = gpd.sjoin_nearest(
        nti_gdf,
        links_proj,
        how="left",
        max_distance=max_distance_m,
        distance_col="match_distance_m",
    )

    matched_tunnel_numbers = set(matched.loc[matched["e_id"].notna(), "tunnel_number"])
    stats = {
        "total_tunnels": len(nti_gdf),
        "matched_tunnels": len(matched_tunnel_numbers),
        "unmatched_tunnels": len(nti_gdf) - len(matched_tunnel_numbers),
        "matched_link_pairs": int(matched["e_id"].notna().sum()),
    }
    stats["match_rate"] = (
        stats["matched_tunnels"] / stats["total_tunnels"] if stats["total_tunnels"] else 0.0
    )

    matched = matched.dropna(subset=["e_id"])
    agg_kwargs: dict = {
        # n_tunnels doubles as the physical bore count: real NTI records are
        # one row per bore (e.g. the Eisenhower/Johnson complex is 2 rows at
        # the same portal location, each its own bore) -- see
        # docs/BRDIGE_COSTS.md step 2.
        "n_tunnels": ("tunnel_number", "count"),
        "match_distance_m_max": ("match_distance_m", "max"),
    }
    if "tunnel_length_m" in matched.columns:
        # docs/BRDIGE_COSTS.md step 2: "Grouped NTI records use longest-bore
        # length" -- max(), NOT sum(), or a 2-bore tunnel's length would be
        # double-counted as if the bores were end-to-end rather than
        # parallel. min() is also kept so a caller can flag unequal bore
        # lengths (spec: "assume equal lengths and flag this" when per-bore
        # lengths aren't separately knowable).
        agg_kwargs["tunnel_length_m"] = ("tunnel_length_m", "max")
        agg_kwargs["tunnel_length_m_min"] = ("tunnel_length_m", "min")
    if "roadway_width_m" in matched.columns:
        agg_kwargs["roadway_width_m"] = ("roadway_width_m", "mean")
    if "lanes" in matched.columns:
        # Total lanes across all matched bores at this link -- the spec's
        # "divide total lanes by bore count" (step 2) needs the sum, not a
        # per-record value.
        agg_kwargs["lanes_total"] = ("lanes", "sum")
    index = matched.groupby("e_id").agg(**agg_kwargs).reset_index()
    index["road_tunnel"] = "yes"
    stats["distinct_links_flagged_as_tunnel"] = len(index)
    stats["total_links"] = len(road_links)
    stats["links_flagged_share"] = (
        stats["distinct_links_flagged_as_tunnel"] / stats["total_links"]
        if stats["total_links"]
        else 0.0
    )
    return index, stats


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--nti", type=Path, required=True)
    ap.add_argument("--road-links", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--max-distance", type=float, default=100.0)
    args = ap.parse_args()

    index, stats = build_tunnel_index(args.nti, args.road_links, max_distance_m=args.max_distance)
    print(f"NTI tunnels: {stats['total_tunnels']}")
    print(
        f"Matched within {args.max_distance}m: {stats['matched_tunnels']} "
        f"({stats['match_rate']:.1%})"
    )
    print(f"Unmatched: {stats['unmatched_tunnels']}")
    print(
        f"FAF5 links flagged as tunnel: {stats['distinct_links_flagged_as_tunnel']} "
        f"of {stats['total_links']} ({stats['links_flagged_share']:.4%})"
    )
    if stats["match_rate"] < 0.3:
        print(
            "WARNING: tunnel match rate below 30% -- check CRS/coverage and --max-distance."
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    index.to_parquet(args.output, index=False)
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
