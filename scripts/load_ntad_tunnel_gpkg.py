#!/usr/bin/env python3
"""Load NTAD National Tunnel Inventory (.gpkg) to a normalized parquet.

Same role as load_ntad_bridge_gdb.py for bridges. Portal lat/lon become the
points used by build_nti_tunnel_index.py (nearest FAF5 link within buffer).

Usage::

    python scripts/load_ntad_tunnel_gpkg.py \\
        --input /path/to/NTAD_National_Tunnel_Inventory.gpkg \\
        --output /path/to/nti_tunnels.parquet
"""

from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import pandas as pd


def load_ntad_tunnels(
    input_path: Path,
    layer: str = "National_Tunnel_Inventory",
) -> pd.DataFrame:
    if not input_path.exists():
        raise FileNotFoundError(f"NTAD tunnel inventory not found: {input_path}")
    gdf = gpd.read_file(input_path, layer=layer)

    # Prefer portal attribute fields; fall back to geometry if present.
    lat = pd.to_numeric(gdf.get("portal_latitude_i13"), errors="coerce")
    lon = pd.to_numeric(gdf.get("portal_longitude_i14"), errors="coerce")
    if gdf.geometry is not None:
        cent = gdf.geometry
        lat = lat.fillna(cent.y)
        lon = lon.fillna(cent.x)

    # NTI coding-guide items G.1 (tunnel length) and G.3 (roadway width,
    # curb-to-curb) are recorded in FEET, not meters -- confirmed empirically
    # (not assumed) against 5 real named tunnels in this exact file before
    # the fix: Eisenhower/Johnson Tunnel (CO) raw G.1 ~8856/8959 matches the
    # real published length in FEET (1.7 mi tunnel, two bores of slightly
    # different length) while the real length in meters is ~2700; Holland
    # Tunnel (NJ/NY) raw G.1 8556 matches its real 8,558 ft length exactly
    # (real meters ~2600); Lincoln Tunnel center tube raw G.1 8216 matches
    # its real 8,216 ft length exactly. Likewise raw G.3 20.0/28.8 ft for
    # Holland/Eisenhower are plausible curb-to-curb widths for 2-lane bores;
    # as meters they would be implausibly wide (66/94 ft). Converted to real
    # meters here (0.3048 m/ft) so this column matches its name and the rest
    # of the codebase's meter convention -- see docs/BRDIGE_COSTS.md step 2
    # ("NTI length G.1 is feet; convert using 0.3048 / 1000").
    _FT_TO_M = 0.3048
    df = pd.DataFrame(
        {
            "tunnel_number": gdf["tunnel_number_i1"].astype(str).str.strip(),
            "tunnel_name": gdf["tunnel_name_i2"].astype(str).str.strip(),
            "state": gdf["state_code_i3"].astype(str).str.strip(),
            "latitude": lat,
            "longitude": lon,
            "tunnel_length_m": pd.to_numeric(gdf.get("tunnel_length_g1"), errors="coerce") * _FT_TO_M,
            "roadway_width_m": pd.to_numeric(
                gdf.get("roadway_width_curb_to_curb_g3"), errors="coerce"
            )
            * _FT_TO_M,
            "lanes": pd.to_numeric(gdf.get("total_number_of_lanes_a3"), errors="coerce"),
            "year_built": pd.to_numeric(gdf.get("year_built_a1"), errors="coerce"),
            "service_in_tunnel": pd.to_numeric(
                gdf.get("service_in_tunnel_a8"), errors="coerce"
            ),
            "functional_class": pd.to_numeric(
                gdf.get("functional_classification_c7"), errors="coerce"
            ),
            "nhs": pd.to_numeric(gdf.get("nhs_designation_c5"), errors="coerce"),
            "facility_carried": gdf.get("facility_carried_i10", pd.Series(dtype=str))
            .astype(str)
            .str.strip(),
        }
    )

    before = len(df)
    df = df.dropna(subset=["latitude", "longitude"]).reset_index(drop=True)
    bad = (df["latitude"] == 0) & (df["longitude"] == 0)
    df = df.loc[~bad].reset_index(drop=True)
    dropped = before - len(df)
    if dropped:
        print(f"Dropped {dropped} tunnels with unrecorded/zero coordinates.")
    return df


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", type=Path, required=True)
    ap.add_argument("--layer", default="National_Tunnel_Inventory")
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()

    df = load_ntad_tunnels(args.input, layer=args.layer)
    print(f"Total: {len(df)} tunnels across {df['state'].nunique()} states/territories.")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(args.output, index=False)
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
