#!/usr/bin/env python3
"""Patch road_bridge/averageWidth onto an already-converted faf5_road_links.gpq.

faf5_network.py's convert_faf5_links() now applies the NBI bridge index
correctly for any FRESH conversion from the raw FAF5 geodatabase -- but the
raw source geodatabase used for this project's existing faf5_road_links.gpq
could not be located (checked Hopper scratch and the local machine,
2026-08-17), so a full from-scratch reconversion isn't available. This
script instead patches the two affected columns directly onto the existing,
already-converted file, calling the exact same
resiflow.preprocess.faf5_network.apply_bridge_index() function
convert_faf5_links() uses -- kept as a single source of truth so the two
paths can never silently diverge.

Writes to a NEW path -- verify row counts and a spot-check match rate before
swapping it in for the live faf5_road_links.gpq (same pattern already used
this project for odpfc_edge_index's sort).

Usage::

    python scripts/patch_faf5_bridge_attributes.py \\
        --road-links /path/to/faf5_road_links.gpq \\
        --bridge-index /path/to/faf5_bridge_index.parquet \\
        --output /path/to/faf5_road_links_bridge_patched.gpq
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from resiflow.preprocess.faf5_network import apply_bridge_index  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--road-links", type=Path, required=True)
    parser.add_argument("--bridge-index", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    links = gpd.read_parquet(args.road_links)
    bridge_index = pd.read_parquet(args.bridge_index)

    before_bridges = int((links.get("road_bridge") == "yes").sum()) if "road_bridge" in links.columns else 0
    patched = apply_bridge_index(links, bridge_index)
    after_bridges = int((patched["road_bridge"] == "yes").sum())

    print(f"Links: {len(patched)} (unchanged row count: {len(patched) == len(links)})")
    print(f"road_bridge='yes' before patch: {before_bridges}")
    print(f"road_bridge='yes' after patch: {after_bridges} ({after_bridges / len(patched):.2%} of links)")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    patched.to_parquet(args.output, index=False)
    print(f"Wrote {args.output}")
    print()
    print("Verify before swapping in:")
    print(f"  python -c \"import geopandas as gpd; a=gpd.read_parquet('{args.road_links}'); "
          f"b=gpd.read_parquet('{args.output}'); print(len(a), len(b), (a.e_id==b.e_id).all())\"")
    print("Once confirmed, swap in manually (not done automatically by this script):")
    print(f"  mv {args.road_links} {args.road_links}.pre_bridge_fix_backup")
    print(f"  mv {args.output} {args.road_links}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
