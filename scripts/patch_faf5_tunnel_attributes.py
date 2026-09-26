#!/usr/bin/env python3
"""Patch road_tunnel / tunnel_length_m / road_label onto faf5_road_links.gpq.

Primary: NTI tunnel index from scripts/build_nti_tunnel_index.py
(existence + tunnel_length_m). Fallback: HPMS STRUCTURE_TYPE==2 (existence
only — no length; costing must not invent tunnel_length_m).

Writes a NEW sibling path — do not overwrite production until counts are reviewed.

Usage::

    python scripts/patch_faf5_tunnel_attributes.py \\
        --road-links /path/to/faf5_road_links.gpq \\
        --nti-index /path/to/faf5_tunnel_index.parquet \\
        --on-conflict prefer_tunnel \\
        --output /path/to/faf5_road_links_tunnel_patched.gpq
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

from resiflow.preprocess.faf5_network import (  # noqa: E402
    apply_tunnel_flags,
    apply_tunnel_index,
    derive_road_label,
    tunnel_e_ids_from_hpms_enriched,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--road-links", type=Path, required=True)
    parser.add_argument("--nti-index", type=Path, default=None)
    parser.add_argument("--hpms-enriched", type=Path, default=None)
    parser.add_argument(
        "--on-conflict",
        choices=("error", "prefer_tunnel", "prefer_bridge"),
        default="prefer_tunnel",
        help="When a link is both road_bridge=yes and road_tunnel=yes",
    )
    parser.add_argument("--conflict-out", type=Path, default=None, help="Write conflicting e_ids CSV")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if not args.road_links.exists():
        raise FileNotFoundError(f"--road-links not found: {args.road_links}")
    if args.nti_index is None and args.hpms_enriched is None:
        raise SystemExit("Provide --nti-index and/or --hpms-enriched")

    links = gpd.read_parquet(args.road_links)
    before = int((links.get("road_tunnel") == "yes").sum()) if "road_tunnel" in links.columns else 0

    if args.nti_index is not None:
        if not args.nti_index.exists():
            raise FileNotFoundError(f"--nti-index not found: {args.nti_index}")
        idx = pd.read_parquet(args.nti_index)
        patched = apply_tunnel_index(links, idx)
        source = f"NTI index ({len(idx)} rows; tunnel_length_m attached)"
    else:
        if not args.hpms_enriched.exists():
            raise FileNotFoundError(f"--hpms-enriched not found: {args.hpms_enriched}")
        tunnel_ids = tunnel_e_ids_from_hpms_enriched(args.hpms_enriched)
        patched = apply_tunnel_flags(links, tunnel_ids)
        patched["tunnel_length_m"] = pd.NA
        patched["tunnel_fraction"] = pd.NA
        source = (
            f"HPMS STRUCTURE_TYPE=2 fallback ({len(tunnel_ids)} e_ids; "
            "no tunnel_length_m — prefer NTI for costing)"
        )

    # Capture conflicts before derive_road_label clears one flag.
    bridge = (
        patched["road_bridge"].astype(str).str.strip().str.lower().eq("yes")
        if "road_bridge" in patched.columns
        else pd.Series(False, index=patched.index)
    )
    tunnel = patched["road_tunnel"].astype(str).str.strip().str.lower().eq("yes")
    conflict = bridge & tunnel
    n_conflict = int(conflict.sum())
    if n_conflict:
        conflict_ids = patched.loc[conflict, "e_id"].astype(str)
        print(f"WARNING: {n_conflict} links flagged both bridge and tunnel")
        if args.conflict_out is not None:
            args.conflict_out.parent.mkdir(parents=True, exist_ok=True)
            conflict_ids.to_frame("e_id").to_csv(args.conflict_out, index=False)
            print(f"Wrote conflict list: {args.conflict_out}")

    patched = derive_road_label(patched, on_conflict=args.on_conflict)
    after = int((patched["road_tunnel"] == "yes").sum())
    n_with_len = int(pd.to_numeric(patched.get("tunnel_length_m"), errors="coerce").notna().sum())

    print(f"Links: {len(patched)} (unchanged row count: {len(patched) == len(links)})")
    print(f"Source: {source}")
    print(f"road_tunnel='yes' before patch: {before}")
    print(f"road_tunnel='yes' after patch: {after} ({after / len(patched):.4%} of links)")
    print(f"tunnel_length_m present: {n_with_len}")
    if n_conflict:
        print(f"Conflicts resolved via on_conflict={args.on_conflict!r}: {n_conflict}")
    print(f"road_label value counts:\n{patched['road_label'].value_counts()}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    patched.to_parquet(args.output, index=False)
    print(f"Wrote {args.output}")
    print("Verify before swapping production (not done by this script).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
