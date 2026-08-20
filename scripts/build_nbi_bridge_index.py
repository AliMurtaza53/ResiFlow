#!/usr/bin/env python3
"""Spatially join NBI bridge structures onto FAF5 road links.

Replaces the current unconditional ``road_bridge = 'no'`` stub in
faf5_network.py's ``DEFAULTS`` with a real, sourced attribute -- see
parameter_diff_final.xlsx item 36 and docs/VA_MULTIHAZARD_COMPARISON.md for
the diagnosis: FAF5's own schema carries no bridge/structure field at all
(confirmed by reading its documented schema in faf5_network.py's own
docstring), so every link in every hazard run this project has produced so
far has priced bridge damage at the ordinary-road rate. DAFNI-NIRD's original
bridge-costing code (compute_damage_values / format_intersections in Script
3, present since ResiFlow's bootstrap commit) already expects a real
``road_bridge`` attribute and has always worked correctly when given one --
DAFNI-NIRD's GB source got this for free from OS MasterMap's structure
attribute; FAF5 has no equivalent, hence this join.

Method: for each NBI structure (see scripts/download_nbi_bridges.py), find
the nearest FAF5 link within --max-distance metres. This is a proximity
match, not a route-name match -- NBI's FACILITY_CARRIED free-text field
("'I-95'", "'US ROUTE 1'", "'SR 100'" with inconsistent formatting) doesn't
reliably crosswalk against FAF5's numeric class codes, so route-name
matching was judged too fragile for a first pass (documented limitation,
not silently skipped). A bridge structure's mapped point is expected to sit
very close to the road centerline it carries, so proximity alone should be
a strong signal; --max-distance defaults to 100m as a generous-but-bounded
tolerance given FAF5's simplified strategic-network geometry (not surveyed
centerlines).

Where multiple NBI structures match the same e_id (a FAF5 link spanning
several short physical structures, common for FAF5's aggregated strategic
geometry), deck_width_m is averaged and structure_length_m is summed --
representing one link's total bridge frontage, not any single structure's
exact dimensions. This is a real approximation, not a source value; flagged
in the output's own docstring/README rather than presented as measured.

Diagnostic, not (yet) a matching change: the output also carries
n_class_inconsistent per link -- how many of its matched structures have
NBI is_ramp disagreeing with the link's own road_classification=='motorway_link'.
Proximity-only matching can attach a structure to a semantically unrelated
link when the structure's true facility isn't in FAF5 at all (confirmed via
ArcGIS Pro visual QA, 2026-08-19: a non-ramp parkway bridge in Loudoun
County, VA matched to a nearby off-ramp because the parkway itself isn't a
FAF5 road). A high disagreement rate on a link doesn't necessarily mean
delete the match -- often there is no better candidate -- but it does mean
treat that link's bridge attribute as lower-confidence. See
build_bridge_index()'s class_consistent computation.

Usage::

    python scripts/build_nbi_bridge_index.py \\
        --nbi /path/to/nbi_bridges_2024.parquet \\
        --road-links /path/to/faf5_road_links.gpq \\
        --output /path/to/faf5_bridge_index.parquet \\
        --max-distance 100
"""

from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

TARGET_CRS = "EPSG:9311"  # US National Atlas Equal Area -- project standard


def build_bridge_index(
    nbi_path: Path,
    road_links_path: Path,
    *,
    max_distance_m: float = 100.0,
) -> tuple[pd.DataFrame, dict]:
    nbi = pd.read_parquet(nbi_path)
    road_links = gpd.read_parquet(road_links_path)

    if "e_id" not in road_links.columns:
        raise KeyError(f"{road_links_path} has no e_id column")

    nbi_gdf = gpd.GeoDataFrame(
        nbi,
        geometry=[Point(lon, lat) for lon, lat in zip(nbi["longitude"], nbi["latitude"])],
        crs="EPSG:4326",
    ).to_crs(TARGET_CRS)

    link_cols = ["e_id", "geometry"]
    has_classification = "road_classification" in road_links.columns
    if has_classification:
        link_cols.append("road_classification")
    links_proj = road_links[link_cols].copy()
    if links_proj.crs is None:
        raise ValueError(f"{road_links_path} has no CRS set -- cannot buffer-match in metres")
    links_proj = links_proj.to_crs(TARGET_CRS)

    matched = gpd.sjoin_nearest(
        nbi_gdf,
        links_proj,
        how="left",
        max_distance=max_distance_m,
        distance_col="match_distance_m",
    )

    # Diagnostic, not (yet) used to change the match itself: does the matched
    # link's own class agree with whether the structure is a ramp? Proximity
    # alone can attach a structure to a semantically unrelated nearby link
    # when the structure's true facility isn't in FAF5 at all (e.g. a named
    # parkway bridge, near an off-ramp, where the parkway itself isn't a
    # strategic-network road) -- confirmed via ArcGIS Pro visual QA,
    # 2026-08-19 (Loudoun County, VA: a "River Creek Pkwy" bridge, not a
    # ramp, matched to a FAF5 link classified Class_Description=Ramp because
    # its actual road wasn't in the network and the ramp was merely the
    # nearest thing within range). 'motorway_link' is ResiFlow's own
    # road_classification value for FAF5 Class 21/22 (System Ramp/Ramp) --
    # see faf5_network.py's CLASS_MAPPING.
    if has_classification and "is_ramp" in matched.columns:
        link_is_ramp_class = matched["road_classification"] == "motorway_link"
        matched["class_consistent"] = (matched["is_ramp"] == link_is_ramp_class).astype("boolean")
        matched.loc[matched["e_id"].isna(), "class_consistent"] = pd.NA
    else:
        matched["class_consistent"] = pd.array([pd.NA] * len(matched), dtype="boolean")

    # sjoin_nearest returns every tied nearest match, not just one -- this is
    # correct and expected, not a bug: FAF5 (like the toy Sioux Falls network,
    # confirmed by direct inspection) represents each direction of a
    # bidirectional road as a separate e_id sharing identical geometry, so a
    # single physical bridge legitimately ties at distance 0 to both
    # directional links and should flag both. Count matched *structures* by
    # unique structure_number, not by output row, so this doesn't read as a
    # rate exceeding 100%.
    matched_structure_numbers = set(matched.loc[matched["e_id"].notna(), "structure_number"])
    stats = {
        "total_structures": len(nbi_gdf),
        "matched_structures": len(matched_structure_numbers),
        "unmatched_structures": len(nbi_gdf) - len(matched_structure_numbers),
        "matched_link_pairs": int(matched["e_id"].notna().sum()),
    }
    stats["match_rate"] = (
        stats["matched_structures"] / stats["total_structures"] if stats["total_structures"] else 0.0
    )

    consistency_known = matched.loc[matched["e_id"].notna(), "class_consistent"].dropna()
    if len(consistency_known):
        stats["class_consistency_checked_pairs"] = int(len(consistency_known))
        stats["class_consistency_rate"] = float(consistency_known.mean())
    else:
        stats["class_consistency_checked_pairs"] = 0
        stats["class_consistency_rate"] = None

    matched = matched.dropna(subset=["e_id"])
    index = (
        matched.groupby("e_id")
        .agg(
            deck_width_m=("deck_width_m", "mean"),
            structure_length_m=("structure_length_m", "sum"),
            n_structures=("structure_number", "count"),
            match_distance_m_max=("match_distance_m", "max"),
            n_class_inconsistent=("class_consistent", lambda s: int((s == False).fillna(False).sum())),  # noqa: E712
        )
        .reset_index()
    )
    index["road_bridge"] = "yes"

    stats["distinct_links_flagged_as_bridge"] = len(index)
    stats["total_links"] = len(road_links)
    stats["links_flagged_share"] = (
        stats["distinct_links_flagged_as_bridge"] / stats["total_links"] if stats["total_links"] else 0.0
    )

    return index, stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--nbi", type=Path, required=True, help="National bridges parquet from download_nbi_bridges.py")
    parser.add_argument("--road-links", type=Path, required=True, help="FAF5 road_links.gpq")
    parser.add_argument("--output", type=Path, required=True, help="Output e_id-keyed bridge index parquet")
    parser.add_argument("--max-distance", type=float, default=100.0, help="Max match distance in metres (default 100)")
    args = parser.parse_args()

    index, stats = build_bridge_index(args.nbi, args.road_links, max_distance_m=args.max_distance)

    print(f"NBI structures: {stats['total_structures']}")
    print(f"Matched within {args.max_distance}m: {stats['matched_structures']} "
          f"({stats['match_rate']:.1%})")
    print(f"Unmatched (no FAF5 link within range): {stats['unmatched_structures']}")
    print(f"(structure, link) match pairs: {stats['matched_link_pairs']} -- exceeds matched "
          f"structures when a bridge ties to both directions of a bidirectional link pair "
          f"sharing identical geometry; expected, not an error.")
    print(f"FAF5 links flagged as bridge: {stats['distinct_links_flagged_as_bridge']} "
          f"of {stats['total_links']} ({stats['links_flagged_share']:.2%})")

    if stats["class_consistency_rate"] is not None:
        print(
            f"Class consistency (structure is_ramp vs. matched link's "
            f"road_classification=='motorway_link'): "
            f"{stats['class_consistency_rate']:.1%} agree "
            f"({stats['class_consistency_checked_pairs']} pairs checked). "
            f"Disagreement doesn't necessarily mean the match is wrong -- it can "
            f"mean the structure's true road simply isn't in FAF5 at all, so the "
            f"nearest link is the best available fallback; see build_bridge_index()'s "
            f"class_consistent comment for the ArcGIS Pro example that motivated this."
        )
    else:
        print(
            "Class consistency check skipped -- road_links has no "
            "road_classification column and/or nbi has no is_ramp column."
        )

    if stats["match_rate"] < 0.5:
        print(
            "WARNING: match rate below 50% -- check road_links CRS/coverage and "
            "--max-distance before trusting this index.",
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    index.to_parquet(args.output, index=False)
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
