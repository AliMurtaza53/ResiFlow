#!/usr/bin/env python3
"""Add ``faf5_class`` (raw FAF5 ``Class`` code) to an already-converted faf5_road_links.gpq.

The converted network's ``road_classification`` collapses several FAF5 classes
into one label (23 -> 'primary'; 16/17/18/19/36/41 -> 'service'; 33 ->
'motorway'), which loses the distinctions the winter-storm clearance model
(T33) is keyed on. This script joins the raw ``Class`` back on ``e_id``
(== raw FAF5 ``ID``) and keeps ``road_classification`` UNCHANGED -- both
columns coexist.

Same convention as scripts/patch_faf5_bridge_attributes.py: writes to a NEW
path and verifies; the swap into the live file is a separate, explicit step.

Usage::

    python scripts/add_faf5_class_to_network.py \\
        --road-links /path/to/faf5_road_links.gpq \\
        --gdb /path/to/FAF5Network.gdb \\
        --output /path/to/faf5_road_links_with_class.gpq
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import geopandas as gpd
import pyogrio

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from resiflow.preprocess.faf5_network import attach_faf5_class  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--road-links", type=Path, required=True)
    parser.add_argument("--gdb", type=Path, required=True, help="Path to FAF5Network.gdb")
    parser.add_argument("--layer", default="FAF5_Links")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    links = gpd.read_parquet(args.road_links)
    raw = pyogrio.read_dataframe(args.gdb, layer=args.layer, read_geometry=False, columns=["ID", "Class"])

    patched = attach_faf5_class(links, raw)

    # --- verification (fails loudly rather than writing a bad file) ---
    assert len(patched) == len(links), "row count changed"
    assert (patched["e_id"].to_numpy() == links["e_id"].to_numpy()).all(), "row order changed"
    for col in links.columns:
        if col == "geometry":
            continue
        same = (patched[col].to_numpy() == links[col].to_numpy()) | (patched[col].isna().to_numpy() & links[col].isna().to_numpy())
        assert same.all(), f"existing column {col!r} was modified"
    assert patched.crs == links.crs, "CRS changed"

    n_null = int(patched["faf5_class"].isna().sum())
    print(f"Links: {len(patched)} (row count unchanged)")
    print(f"faf5_class populated: {len(patched) - n_null}; null (raw Class is null): {n_null}")
    print("faf5_class value counts:")
    print(patched["faf5_class"].value_counts(dropna=False).sort_index().to_string())

    args.output.parent.mkdir(parents=True, exist_ok=True)
    patched.to_parquet(args.output, index=False)
    print(f"Wrote {args.output}")
    print("Swap in manually once verified (not done by this script):")
    print(f"  mv {args.road_links} {args.road_links}.pre_faf5_class_backup")
    print(f"  mv {args.output} {args.road_links}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
