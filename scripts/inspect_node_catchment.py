#!/usr/bin/env python3
"""Inspect a network node's direct edges and one-hop downstream connectivity.

Used to answer "is this node's overload a genuine access bottleneck, or
does it sit at a well-connected interchange and just need a finer
catchment split?" -- the question raised for LA's worst remaining node
(42799, 4.99x overload_ratio even after home/work subarea splitting)
after the county-connector remedy work.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import geopandas as gpd
import pandas as pd

LOGGER = logging.getLogger(__name__)

_DISPLAY_COLUMNS = ["e_id", "from_id", "to_id", "road_classification", "assignment_tier", "hpms_fclass", "lanes", "road_label", "Road_Name"]


def direct_edges(road_links: pd.DataFrame, node_id: str) -> pd.DataFrame:
    """Edges with node_id as either endpoint."""
    return road_links[(road_links["from_id"].astype(str) == node_id) | (road_links["to_id"].astype(str) == node_id)]


def one_hop_neighbors(touching: pd.DataFrame, node_id: str) -> set[str]:
    """Node IDs one hop away from node_id, per its direct edges."""
    neighbors = set(touching["from_id"].astype(str)) | set(touching["to_id"].astype(str))
    neighbors.discard(node_id)
    return neighbors


def downstream_edges(road_links: pd.DataFrame, node_id: str, neighbors: set[str]) -> pd.DataFrame:
    """Edges touching node_id's one-hop neighbors, excluding node_id's own direct edges."""
    from_str = road_links["from_id"].astype(str)
    to_str = road_links["to_id"].astype(str)
    touches_neighbor = from_str.isin(neighbors) | to_str.isin(neighbors)
    touches_node = (from_str == node_id) | (to_str == node_id)
    return road_links[touches_neighbor & ~touches_node]


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--road-links", required=True, help="faf5_road_links.gpq")
    parser.add_argument("--node-id", required=True)
    parser.add_argument("--subarea-crosswalk", action="append", default=[], help="Optional crosswalk CSV(s) (home/work) to report which subarea this node serves; repeatable")
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
    args = build_arg_parser().parse_args(argv)

    road_links = gpd.read_parquet(args.road_links)
    node_id = args.node_id

    for crosswalk_path in args.subarea_crosswalk:
        crosswalk = pd.read_csv(crosswalk_path, dtype={"node_id": str})
        hit = crosswalk[crosswalk["node_id"] == node_id]
        if not hit.empty:
            print(f"--- subarea role in {Path(crosswalk_path).name} ---")
            print(hit.to_string(index=False))

    touching = direct_edges(road_links, node_id)
    print(f"\nDirect edges touching node {node_id}: {len(touching)}")
    print(touching[[c for c in _DISPLAY_COLUMNS if c in touching.columns]].to_string(index=False))

    neighbors = one_hop_neighbors(touching, node_id)
    print(f"\nOne-hop neighbor nodes: {sorted(neighbors)}")

    downstream = downstream_edges(road_links, node_id, neighbors)
    print(f"Edges touching those one-hop neighbors (excluding node {node_id}'s own direct edges): {len(downstream)}")
    print(downstream[[c for c in _DISPLAY_COLUMNS if c in downstream.columns]].head(30).to_string(index=False))

    if "assignment_tier" in downstream.columns:
        print(f"\nDownstream assignment_tier breakdown:\n{downstream['assignment_tier'].value_counts()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
