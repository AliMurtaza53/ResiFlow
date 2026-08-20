#!/usr/bin/env python3
"""Load NBI structures from the official NTAD file geodatabase distribution,
producing the same output schema as download_nbi_bridges.py.

Preferred over download_nbi_bridges.py's per-state scraping where available:
this is the authoritative BTS/NTAD distribution (data dictionary DOI
https://doi.org/10.21949/1519105, data via
https://services.arcgis.com/xOi1kZaI0eWDREZv/arcgis/rest/services/
NTAD_National_Bridge_Inventory/FeatureServer/0), confirmed 2026-08-18:

  - Already-decoded decimal-degree coordinates (LATDD/LONGDD) and a real
    point geometry -- no DMS packed-coordinate parsing needed at all (the
    class of bug download_nbi_bridges.py had to specifically guard against
    for Guam's eastern-hemisphere sign and malformed DE records doesn't
    apply here; verified LATDD/LONGDD for the same Wilmington, DE structure
    used in that module's tests matches to 6 decimal places).
  - More current: 624,193 structures ("as of June 20, 2025" per the
    service's own description) vs. 621,533 from download_nbi_bridges.py's
    2024-dated per-state files.
  - A single versioned, citable download rather than 54 scraped files from
    a page with no formal versioning.

Usage::

    python scripts/load_ntad_bridge_gdb.py \\
        --gdb /path/to/extracted/xxxxxxxx.gdb \\
        --output /path/to/nbi_bridges_ntad.parquet
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from download_nbi_bridges import (  # noqa: E402
    ROUTE_PREFIX_LABELS,
    SERVICE_LEVEL_LABELS,
    FUNCTIONAL_CLASS_LABELS,
    _clean_deck_width,
)


def load_ntad_bridges(gdb_path: Path, layer: str = "National_Bridge_Inventory") -> pd.DataFrame:
    gdf = gpd.read_file(gdb_path, layer=layer)

    df = pd.DataFrame(
        {
            "state": gdf["STATE_CODE_001"].astype(str).str.strip(),
            "structure_number": gdf["STRUCTURE_NUMBER_008"].astype(str).str.strip(),
            "facility_carried": gdf["FACILITY_CARRIED_007"].astype(str).str.strip().str.strip("'"),
            "location": gdf["LOCATION_009"].astype(str).str.strip().str.strip("'"),
            "latitude": pd.to_numeric(gdf["LATDD"], errors="coerce"),
            "longitude": pd.to_numeric(gdf["LONGDD"], errors="coerce"),
            "deck_width_m": _clean_deck_width(gdf["DECK_WIDTH_MT_052"]),
            "structure_length_m": pd.to_numeric(gdf["STRUCTURE_LEN_MT_049"], errors="coerce"),
            # Added 2026-08-20 for HAZUS 6.1 bridge classification (Table
            # 7-1) -- see download_nbi_bridges.py's identical fields for the
            # skew_degrees==99 caveat (NBI's "major variation" convention,
            # not a literal 99 degrees).
            "main_unit_spans": pd.to_numeric(gdf["MAIN_UNIT_SPANS_045"], errors="coerce"),
            "max_span_length_m": pd.to_numeric(gdf["MAX_SPAN_LEN_MT_048"], errors="coerce"),
            "skew_degrees": pd.to_numeric(gdf["DEGREES_SKEW_034"], errors="coerce"),
            "structure_kind_code": gdf["STRUCTURE_KIND_043A"].astype(str).str.strip(),
            "structure_type_code": gdf["STRUCTURE_TYPE_043B"].astype(str).str.strip().str.zfill(2),
            "year_built": pd.to_numeric(gdf["YEAR_BUILT_027"], errors="coerce"),
            "owner": gdf["OWNER_022"].astype(str).str.strip(),
            "maintenance": gdf["MAINTENANCE_021"].astype(str).str.strip(),
            "on_nhs": gdf["HIGHWAY_SYSTEM_104"].astype(str).str.strip(),
        }
    )
    df["route_prefix"] = gdf["ROUTE_PREFIX_005B"].astype(str).str.strip().map(ROUTE_PREFIX_LABELS)
    df["service_level_raw_code"] = gdf["SERVICE_LEVEL_005C"].astype(str).str.strip()
    df["service_level"] = df["service_level_raw_code"].map(SERVICE_LEVEL_LABELS)
    df["functional_class"] = (
        gdf["FUNCTIONAL_CLASS_026"].astype(str).str.strip().str.zfill(2).map(FUNCTIONAL_CLASS_LABELS)
    )
    df["is_ramp"] = df["service_level_raw_code"] == "7"
    df["is_ramp_by_name"] = df["facility_carried"].str.contains("RAMP", case=False, na=False)

    before = len(df)
    df = df.dropna(subset=["latitude", "longitude"]).reset_index(drop=True)
    dropped = before - len(df)
    if dropped:
        print(f"Dropped {dropped} structures with unrecorded coordinates.")

    return df


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--gdb", type=Path, required=True, help="Path to the extracted .gdb directory")
    parser.add_argument("--layer", default="National_Bridge_Inventory")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    df = load_ntad_bridges(args.gdb, layer=args.layer)
    print(f"Total: {len(df)} bridges across {df['state'].nunique()} states/territories.")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(args.output, index=False)
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
