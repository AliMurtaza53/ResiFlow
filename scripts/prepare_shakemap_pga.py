#!/usr/bin/env python3
"""Convert the real 2011 Mineral, VA M5.8 USGS ShakeMap PGA grid to a
georeferenced, linear-g GeoTIFF ready for scripts/align_hazard_rasters.py.

Source: M5_8_ShakeMap_raster.zip (ESRI BIL .flt/.hdr pairs -- USGS ShakeMap's
raw "raster" download format), containing mean/std grids for MMI, PGA, PGV,
and PSA at 0.3/1.0/3.0s. This script only needs pga_mean.flt (the layer the
existing earthquake fragility curve consumes as g_pga).

Two things this grid needs before it can go through align_hazard_rasters.py's
linear --unit-scale:

1. UNITS: ShakeMap's internal convention (confirmed via USGS's own shakelib
   docs, shakelib.gmice.gmice: "Ground motion amplitude; natural log units;
   g for PGA and PSA, cm/s for PGV") stores PGA/PSA as ln(g), not linear g --
   confirmed independently by the raw values here being all negative
   (ln of a sub-1 g quantity). exp() is a nonlinear transform,
   align_hazard_rasters.py's --unit-scale is a linear multiplier only, so
   this has to happen here, upstream of that generic tool. MMI is NOT
   log-transformed in ShakeMap products (confirmed by its raw values already
   sitting on MMI's normal ~1-10 scale) -- do not exponentiate it if it's
   ever added here.

2. GEOREFERENCING: the .hdr gives ULXMAP/ULYMAP/XDIM/YDIM (an ESRI BIL grid
   header) but there is no accompanying .prj in this download, so the CRS
   isn't stated in the data itself. Assumed EPSG:4326 (WGS84 geographic) --
   USGS ShakeMap's standard product CRS -- but this is an ASSUMPTION, not
   read from the file; flagged here and in the alignment docs rather than
   silently baked in.

Coverage caveat: this grid's extent is lon [-83.0, -71.98], lat [33.98, 42.0]
(computed from the .hdr) -- it does NOT reach VA's westernmost ~0.68 degrees
(west of -83.0, roughly the Bristol/Cumberland Gap corner of the VA bbox
lon [-83.68, -74.90]). Pixels in that sliver stay nodata after alignment;
align_hazard_rasters.py doesn't error on partial coverage, but downstream
consumers should know the far-SW corner of VA has no earthquake intensity
value from this source.

Usage::

    python scripts/prepare_shakemap_pga.py \
        --zip inputs/va_multihazard_raw/earthquake/mineral_shakemap/M5_8_ShakeMap_raster.zip \
        --output inputs/va_multihazard_raw/earthquake/mineral_shakemap/pga_g.tif
"""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path

import numpy as np
import rasterio
from affine import Affine

ASSUMED_CRS = "EPSG:4326"


def parse_hdr(hdr_text: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for line in hdr_text.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            try:
                out[parts[0].upper()] = float(parts[1])
            except ValueError:
                continue
    return out


def load_flt_layer(zf: zipfile.ZipFile, stem: str) -> tuple[np.ndarray, dict[str, float]]:
    hdr = parse_hdr(zf.read(f"{stem}.hdr").decode())
    nrows, ncols = int(hdr["NROWS"]), int(hdr["NCOLS"])
    arr = np.frombuffer(zf.read(f"{stem}.flt"), dtype="<f4").reshape(nrows, ncols).copy()
    return arr, hdr


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--zip", type=Path, required=True, help="M5_8_ShakeMap_raster.zip")
    parser.add_argument("--layer", default="pga_mean", help="Grid stem to convert (default: pga_mean)")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    with zipfile.ZipFile(args.zip) as zf:
        arr, hdr = load_flt_layer(zf, args.layer)

    nodata_ln = hdr["NODATA"]
    valid_mask = arr != nodata_ln
    n_valid = int(valid_mask.sum())
    print(f"{args.layer}: shape={arr.shape}, valid={n_valid}/{arr.size} "
          f"({100 * n_valid / arr.size:.1f}%), ln(g) range="
          f"[{arr[valid_mask].min():.4f}, {arr[valid_mask].max():.4f}]")

    pga_g = np.full(arr.shape, np.nan, dtype="float32")
    pga_g[valid_mask] = np.exp(arr[valid_mask].astype("float64")).astype("float32")
    print(f"{args.layer} converted to linear g: range="
          f"[{np.nanmin(pga_g):.4f}, {np.nanmax(pga_g):.4f}], "
          f"mean={np.nanmean(pga_g):.4f}")

    transform = Affine(hdr["XDIM"], 0.0, hdr["ULXMAP"], 0.0, -hdr["YDIM"], hdr["ULYMAP"])

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        args.output,
        "w",
        driver="GTiff",
        height=pga_g.shape[0],
        width=pga_g.shape[1],
        count=1,
        dtype="float32",
        crs=ASSUMED_CRS,
        transform=transform,
        nodata=np.nan,
        compress="deflate",
    ) as dst:
        dst.write(pga_g, 1)

    print(f"Wrote {args.output} (CRS assumed {ASSUMED_CRS} -- no .prj in source zip)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
