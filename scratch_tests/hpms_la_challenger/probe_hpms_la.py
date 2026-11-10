"""One-shot probe: LA County bbox + HPMS CA density in a known sparse box.

ponytail: throwaway probe script; delete once the builder replaces it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pyogrio

COUNTY = Path(r"C:/Users/akothaw/Desktop/data/faf5_data/county_shp/tl_2022_us_county.shp")
HPMS = "/vsizip/C:/Users/akothaw/Desktop/data/faf5_data/HPMS2024.zip/HPMS2024.gdb"
LAYER = "HPMS_FULL_CA_2024"
# Known sparse FAF5 box from the challenger brief (node 36599 area)
SPARSE_LON, SPARSE_LAT = -118.53497, 34.23535
SPARSE_RADIUS_DEG = 2.5 / 111.0  # ~2.5 km box half-width in degrees (rough)


def main() -> int:
    la = pyogrio.read_dataframe(
        COUNTY, where="GEOID='06037'", columns=["GEOID", "NAME", "STATEFP", "COUNTYFP"]
    )
    if len(la) != 1:
        raise SystemExit(f"expected 1 LA County row, got {len(la)}")
    print("LA County:", la.iloc[0].to_dict())
    print("crs:", la.crs)
    bbox = tuple(la.total_bounds)  # minx, miny, maxx, maxy
    print("LA bbox:", bbox)

    layers = pyogrio.list_layers(HPMS)
    ca = [r[0] for r in layers if "CA" in str(r[0]).upper()]
    print(f"HPMS layers total={len(layers)}; CA={ca}")
    if LAYER not in {r[0] for r in layers}:
        raise SystemExit(f"missing layer {LAYER!r}")

    # Sparse-box density check (same claim as the brief)
    sb = (
        SPARSE_LON - SPARSE_RADIUS_DEG,
        SPARSE_LAT - SPARSE_RADIUS_DEG,
        SPARSE_LON + SPARSE_RADIUS_DEG,
        SPARSE_LAT + SPARSE_RADIUS_DEG,
    )
    print("reading sparse box bbox=", sb, "...", flush=True)
    sparse = pyogrio.read_dataframe(
        HPMS,
        layer=LAYER,
        bbox=sb,
        columns=["route_id", "begin_point", "end_point", "f_system", "through_lanes"],
    )
    print(f"sparse-box features: {len(sparse)}")
    if "f_system" in sparse.columns:
        print("f_system counts:\n", sparse["f_system"].value_counts(dropna=False).head(20))
    print("columns:", list(sparse.columns))
    print("crs:", sparse.crs)

    # LA County clip count only (geometry + f_system) — can be large; stream via bbox
    print("reading LA County bbox (count + f_system)...", flush=True)
    la_gdf = pyogrio.read_dataframe(
        HPMS,
        layer=LAYER,
        bbox=bbox,
        columns=["f_system"],
    )
    print(f"LA bbox features: {len(la_gdf)}")
    print("f_system counts:\n", la_gdf["f_system"].value_counts(dropna=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
