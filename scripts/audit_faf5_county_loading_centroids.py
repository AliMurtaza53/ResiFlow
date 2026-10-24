#!/usr/bin/env python3
"""Read-only audit: how many network loading centroids does each county
actually get in the live freight pipeline?

Confirms (or refutes) two things, from the already-produced local files --
this does NOT re-run the freight pipeline or touch its OD/crosswalk/loading
logic:

  1. Which mapping method actually produced the live freight OD: real FAF5
     loading centroids (run_mapping / Method 1) vs the county-shapefile
     nearest-node fallback (map_county_od_via_county_shp). Read straight
     from the pipeline's own summary JSON, not inferred from code.
  2. For each county: how many distinct network loading centroids/nodes it
     was actually assigned (not how many exist nationally). A rich national
     total (~3,100+) can still mean any single large county gets exactly
     one -- this is the number that actually matters for whether freight
     demand concentrates the way passenger demand did.

Usage::

    python scripts/audit_faf5_county_loading_centroids.py \\
        --crosswalk "C:\\Users\\akothaw\\Desktop\\data\\faf5_data\\processed\\bts_county_to_network_centroid_crosswalk_2022.csv" \\
        --summary "C:\\Users\\akothaw\\Desktop\\data\\faf5_data\\processed\\faf5_bts_conus_centroid_od_2022_by_sctg_summary.json" \\
        --output-json "C:\\Users\\akothaw\\Desktop\\data\\faf5_data\\processed\\county_loading_centroid_audit.json"
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def audit(crosswalk_path: Path, summary_path: Path) -> dict:
    crosswalk = pd.read_csv(crosswalk_path, dtype=str)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    mapping_method = summary.get("mapping_method", "unknown (not recorded in this summary)")
    network_centroids_path = summary.get("network_centroids_path")
    unmatched = summary.get("unmatched_zones_before_nearest_fallback")
    unmapped_after_fallback = summary.get("unmapped_after_fallback")

    # a county FIPS is the first 5 chars of detail_zone_id for ordinary
    # (non-subcounty) BTS detail zones; this audit counts DISTINCT assigned
    # node ids per detail_zone_id, not per county, since that's the unit
    # BTS's experimental county product actually loads through.
    per_zone = crosswalk.groupby("detail_zone_id")["assigned_node_id"].nunique()
    centroid_counts = per_zone.value_counts().sort_index()

    la_row = crosswalk[crosswalk["detail_zone_id"] == "06037"]

    result = {
        "mapping_method_used": mapping_method,
        "network_centroids_source": network_centroids_path,
        "unmatched_zones_before_nearest_fallback": unmatched,
        "unmapped_after_fallback": unmapped_after_fallback,
        "total_detail_zones": int(len(per_zone)),
        "zones_with_1_centroid": int(centroid_counts.get(1, 0)),
        "zones_with_2plus_centroids": int(centroid_counts.drop(index=1, errors="ignore").sum()),
        "centroid_count_distribution": {str(k): int(v) for k, v in centroid_counts.items()},
        "la_county_06037": la_row.to_dict(orient="records"),
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--crosswalk", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, default=None)
    args = parser.parse_args()

    result = audit(args.crosswalk, args.summary)
    print(json.dumps(result, indent=2))

    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"\nWrote {args.output_json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
