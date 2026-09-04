#!/usr/bin/env python3
"""Downsample+reproject the real Hurricane Harvey flood-depth grid for a new,
Houston/Harris-County flood case study (NOT a VA source -- see
docs/VA_MULTIHAZARD_COMPARISON.md, "Harvey" section).

Source: Harvey_Depths_3m_Final.gdb.zip, a 39GB-zipped / ~84GB-uncompressed
Esri File Geodatabase raster (150074x140878 px at ~3m/px, EPSG:4269), bounds
lon [-97.877, -93.532] lat [27.444, 31.523] -- confirmed via rasterio to be
the Houston/Harris County Gulf Coast, zero overlap with the VA bbox this
project otherwise uses. Since scenario_param/hazard_type routing doesn't
require a specific region (the road network stays CONUS-scale; only the
hazard raster is region-sized -- same pattern VA already uses), this can be
wired in as its OWN case study rather than forced onto VA's grid.

MUST run against an EXTRACTED (unzipped) copy of the .gdb, not the .zip via
GDAL's /vsizip/ -- confirmed locally (2026-08-03) that even a decimated,
streaming reproject() (rasterio.band() source, never materializing the full
84GB array) times out past 100s reading live from the zip; the FileGDB
raster's block-indexed random access is efficient against a real directory
but not against zip-compressed storage. Unzip first:

    cd /scratch/akothaw/multimodal_hazard_data/inputs_raw
    unzip Harvey_Depths_3m_Final.gdb.zip   # ~84GB extracted, check quota first

No pre-existing reference raster exists for this region (VA's 141-node
reference obviously doesn't apply) -- the target grid is derived directly
from the source's own bounds, reprojected to the project's standard
EPSG:9311, at --resolution (default 50m, matching VA's convention so the two
regions stay comparable if ever plotted side by side; override if 50m proves
too coarse or too large for a first look).

Uses Resampling.average (not bilinear) since this is a large downsample
factor (~17x per axis, ~278x by area) -- averaging correctly incorporates
all ~278 source pixels per output pixel; bilinear would only interpolate
between a handful of nearby ones and could alias.

This script does the reproject+resample to the final target grid itself (via
streaming reproject(), not a full-array read), so unlike the other real-data
hazards its output should be written DIRECTLY to the
inputs/va_multihazard_aligned/<hazard_subtype>/event_1.tif convention --
running it through align_hazard_rasters.py afterwards would just resample a
second time for no benefit, and that script's align_raster() does a full
src.read() first, which is exactly the bottleneck this script exists to
avoid at Harvey's scale.

Usage::

    python scripts/prepare_harvey_depths.py \
        --input /scratch/.../inputs_raw/Harvey_Depths_3m_Final.gdb \
        --output /scratch/.../inputs/va_multihazard_aligned/flood_harvey_houston/event_1.tif \
        --resolution 50
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import Resampling, calculate_default_transform, reproject, transform_bounds

TARGET_CRS = "EPSG:9311"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, required=True, help="Extracted (not zipped) Harvey_Depths_3m_Final.gdb")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resolution", type=float, default=50.0, help="Target resolution in meters (EPSG:9311)")
    args = parser.parse_args()

    t0 = time.time()
    with rasterio.open(args.input) as src:
        print(f"Source: {src.width}x{src.height} px, crs={src.crs}, nodata={src.nodata}, bounds={src.bounds}")

        dst_crs = TARGET_CRS
        dst_transform, dst_width, dst_height = calculate_default_transform(
            src.crs, dst_crs, src.width, src.height, *src.bounds, resolution=args.resolution
        )
        print(f"Target grid ({dst_crs} @ {args.resolution}m): {dst_width}x{dst_height} px "
              f"({dst_width * dst_height / 1e6:.1f}M pixels)")

        dst = np.full((dst_height, dst_width), np.nan, dtype="float32")
        reproject(
            source=rasterio.band(src, 1),
            destination=dst,
            src_transform=src.transform,
            src_crs=src.crs,
            src_nodata=src.nodata,
            dst_transform=dst_transform,
            dst_crs=dst_crs,
            dst_nodata=np.nan,
            resampling=Resampling.average,
        )

    elapsed = time.time() - t0
    valid = dst[~np.isnan(dst)]
    print(f"Reprojected in {elapsed:.1f}s. valid={valid.size}/{dst.size} "
          f"({100 * valid.size / dst.size:.1f}%)")
    if valid.size:
        print(f"depth (m): min={valid.min():.3f} max={valid.max():.3f} "
              f"mean={valid.mean():.3f} median={np.median(valid):.3f} "
              f"p90={np.percentile(valid, 90):.3f} p99={np.percentile(valid, 99):.3f}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        args.output,
        "w",
        driver="GTiff",
        height=dst_height,
        width=dst_width,
        count=1,
        dtype="float32",
        crs=dst_crs,
        transform=dst_transform,
        nodata=np.nan,
        compress="deflate",
    ) as out:
        out.write(dst, 1)
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
