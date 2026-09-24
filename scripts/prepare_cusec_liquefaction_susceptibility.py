#!/usr/bin/env python3
"""Build a HAZUS-scheme liquefaction susceptibility raster for the New Madrid
earthquake scenario (403) from the CUSEC (Central US Earthquake Consortium)
state liquefaction-susceptibility shapefiles already staged in this repo at
``inputs/multihazard_raw/landslide/cusec_sg_liquefaction.zip``.

Source: 8 state geological-survey liquefaction susceptibility maps (AL, AR,
IL, IN, KY, MO, MS, TN), produced for a mid-2000s FEMA/CUSEC catastrophic
planning study of a New Madrid Seismic Zone scenario (confirmed from
MoLiqSusceptibilityMap83.shp.xml's embedded ArcGIS processing lineage:
"...FEMA Catastrophic Planning\\CD\\Missouri\\LiqSusceptMap..."). Each state's
shapefile uses its own native schema (GEOUNIT/ORIGIN_AGE/LITHOLOGY/etc. all
differ state to state), but all 8 share one common field -- ``TYPE``
(``Type`` in two of them) -- confirmed by direct inspection to be a
harmonized 0-5 code, NOT state-specific:

    0 = unclassified / open water (no liquefiable unit mapped)
    1 = Very Low       2 = Low       3 = Moderate       4 = High       5 = Very High

Confirmed directly against Arkansas's own attribute table, which ships BOTH
the numeric code and a text label in the same row (``L_S_Class``):
TYPE 1='Very_Low', 3='Moderate', 4='High', 5='Very_High' (2='Low' absent from
AR's own extent but the same 5-class HAZUS Table 4-8 scale). This is exactly
resiflow's T31 lookup table's own susceptibility_class vocabulary
(VeryLow/Low/Moderate/High/VeryHigh) -- no invented crosswalk, a direct
1:1 match confirmed from source data, not assumed by analogy.

This resolves docs/HAZARD_TABLE_INTEGRATION_RUNBOOK.md's Track A Step 3
blocker ("this project has no liquefaction susceptibility layer") for
exactly the 8-state footprint the New Madrid M7.5 scenario (403) actually
covers -- Mineral (401, VA) and Cascadia (404, WA/OR) have zero overlap with
this dataset and stay unassigned (code 255 / nodata), not backfilled with an
invented default.

Output: a single-band uint8 GeoTIFF, native EPSG:4269 (NAD83 lat/lon --
matching 7 of the 8 source shapefiles; Arkansas's own EPSG:26915 is
reprojected to match, not the other way, since 4269 is the majority and the
project's raster-intersection code (exposure/raster_line.py's
intersect_features_with_raster) reprojects the SAMPLED VALUES to
CONUS_TARGET_CRS internally via snail's build_snail_grid -- the source
raster's own CRS need not match the project's target CRS, only be
self-consistent and correctly georeferenced), at 200m resolution (source
data is dissolved state-level geologic-unit polygons, tens of km across --
200m is already far finer than the source's real precision, not a
downsampling loss). NODATA=255 (no susceptibility class mapped -- distinct
from code 0, "mapped as non-liquefiable/water").

Usage::

    python scripts/prepare_cusec_liquefaction_susceptibility.py \\
        --cusec-zip inputs/multihazard_raw/landslide/cusec_sg_liquefaction.zip \\
        --output inputs/multihazard_aligned/earthquake_new_madrid_m75_scenario_liquefaction/event_1.tif
"""

from __future__ import annotations

import argparse
import tempfile
import zipfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import rasterize
from rasterio.transform import from_origin

_STATE_ZIPS = ("AL", "AR", "IL", "IN", "KY", "MO", "MS", "TN")
_TARGET_CRS = "EPSG:4269"
_RESOLUTION_M_APPROX_DEG = 200.0 / 111_320.0  # ~200m at these latitudes, in decimal degrees
_NODATA = 255


def _load_state_gdf(state_dir: Path) -> gpd.GeoDataFrame:
    shp_paths = list(state_dir.glob("*.shp"))
    if len(shp_paths) != 1:
        raise SystemExit(f"Expected exactly one .shp in {state_dir}, found {shp_paths}")
    gdf = gpd.read_file(shp_paths[0])
    type_col = "TYPE" if "TYPE" in gdf.columns else "Type"
    if type_col not in gdf.columns:
        raise SystemExit(f"{shp_paths[0]} has no TYPE/Type column (columns: {list(gdf.columns)})")
    gdf["susceptibility_code"] = pd.to_numeric(gdf[type_col], errors="coerce")
    gdf = gdf.dropna(subset=["susceptibility_code", "geometry"])
    gdf["susceptibility_code"] = gdf["susceptibility_code"].round().astype(int).clip(0, 5)
    if gdf.crs is None:
        raise SystemExit(f"{shp_paths[0]} has no CRS defined")
    if gdf.crs.to_epsg() != 4269:
        gdf = gdf.to_crs(_TARGET_CRS)
    return gdf[["susceptibility_code", "geometry"]]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cusec-zip", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        with zipfile.ZipFile(args.cusec_zip) as outer:
            for state in _STATE_ZIPS:
                inner_name = f"{state}-liquefaction.zip"
                state_dir = tmp_path / state
                state_dir.mkdir()
                with outer.open(inner_name) as inner_fp:
                    with zipfile.ZipFile(inner_fp) as inner_zip:
                        inner_zip.extractall(state_dir)

        gdfs = []
        for state in _STATE_ZIPS:
            gdf = _load_state_gdf(tmp_path / state)
            gdf["state"] = state
            print(f"{state}: {len(gdf)} polygons, codes {sorted(gdf['susceptibility_code'].unique())}")
            gdfs.append(gdf)

        merged = gpd.GeoDataFrame(pd.concat(gdfs, ignore_index=True), crs=_TARGET_CRS)

    minx, miny, maxx, maxy = merged.total_bounds
    pad = _RESOLUTION_M_APPROX_DEG * 5
    minx, miny, maxx, maxy = minx - pad, miny - pad, maxx + pad, maxy + pad
    width = int(np.ceil((maxx - minx) / _RESOLUTION_M_APPROX_DEG))
    height = int(np.ceil((maxy - miny) / _RESOLUTION_M_APPROX_DEG))
    transform = from_origin(minx, maxy, _RESOLUTION_M_APPROX_DEG, _RESOLUTION_M_APPROX_DEG)

    print(f"Rasterizing {len(merged)} polygons onto a {height}x{width} grid (~200m, {_TARGET_CRS})...")
    shapes = [(geom, code) for geom, code in zip(merged.geometry, merged["susceptibility_code"])]
    raster = rasterize(
        shapes,
        out_shape=(height, width),
        transform=transform,
        fill=_NODATA,
        dtype="uint8",
        all_touched=True,
    )

    n_covered = int((raster != _NODATA).sum())
    print(
        f"Coverage: {n_covered}/{raster.size} pixels ({100 * n_covered / raster.size:.1f}%) "
        f"assigned a susceptibility code; class counts: "
        f"{dict(zip(*np.unique(raster[raster != _NODATA], return_counts=True)))}"
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        args.output,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype="uint8",
        crs=_TARGET_CRS,
        transform=transform,
        nodata=_NODATA,
        compress="deflate",
    ) as dst:
        dst.write(raster, 1)

    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
