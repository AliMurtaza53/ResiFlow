#!/usr/bin/env python3
"""Mosaic+reproject Hurricane Sandy FEMA coastal-flood depth grids (CT/NJ/NY/RI)
into a single Northeast flood case study -- a second real-flood scenario
alongside Harvey (flood_harvey_houston, 304), not a replacement of it in the
pipeline (both stay runnable; only the hazard-footprint comparison figures
swap their flood panel to Sandy -- see scripts/figures/_hazard_footprints_common.py).

Source: 4 separate state-clipped depth grids in
inputs/multihazard_raw/flood/{ct,nj,nys,ri}3m0214c.tif -- confirmed via
rasterio: all EPSG:4269, float32, ~3m/px, same nodata sentinel
(-3.4028230607370965e+38, i.e. np.finfo('float32').min), depths 0-18m
(NJ max ~17.9m). All four are LZW-compressed and >90% nodata by area (each
covers a rectangular bounding box around a state, but Sandy's real
inundation extent is a thin coastal/estuary fringe) -- that combination is
why each file is under 1GB on disk despite raw uncompressed arrays up to
~14GB (NJ: 53694x67048 px). Confirmed 2026-09-10.

Unlike Harvey (one raster), the 4 source rasters' rectangular bounding boxes
overlap (e.g. CT/RI along the CT-RI shoreline, NY/NJ across the Hudson/NY
Harbor) even though their VALID (non-nodata) footprints mostly don't -- each
state's grid only carries real depths over its own mapped inundation extent.
Where an output pixel DOES get valid data from more than one source (shared
coastal water), this script averages them rather than picking one
arbitrarily, since all 4 come from the same event/methodology and there's no
principled reason to prefer one state's grid over another's there.

Like prepare_harvey_depths.py, streams each source individually into the
destination array via reproject()+rasterio.band() (never a full src.read())
-- necessary at NJ's raw array scale even though its file is small on disk
(see above). build_sandy_mosaic() is the reusable core: called here at 50m
for the pipeline's aligned grid, and imported directly by
scripts/figures/_hazard_footprints_common.py at a coarser display resolution
for the comparison figures, so the two never drift out of the same
mosaic/averaging logic.

This script writes DIRECTLY to the
inputs/multihazard_aligned/<hazard_subtype>/event_1.tif convention (like
Harvey) -- running the output back through align_hazard_rasters.py would
just resample a second time for no benefit.

Usage::

    python scripts/prepare_sandy_depths.py \
        --output inputs/multihazard_aligned/flood_sandy_northeast/event_1.tif \
        --resolution 50
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import Affine, from_origin
from rasterio.warp import Resampling, reproject, transform_bounds

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from resiflow.geo_runtime import configure_geo_runtime

# Must run before any transform_bounds()/CRS lookup below -- confirmed on
# Hopper's `nird` conda env (2026-09-11) that without this, PROJ can't find
# proj.db and every CRS operation raises CPLE_AppDefinedError. Harmless
# locally (this session's local runs never hit it -- rasterio's own bundled
# PROJ data happened to be found by default there), but not something to
# skip just because it wasn't needed on one machine. Same fix
# align_hazard_rasters.py already relies on via rasterio_env() -- see
# docs/geo_projection_conus.md.
configure_geo_runtime()

DEFAULT_RAW_DIR = REPO_ROOT / "inputs" / "multihazard_raw" / "flood"
SANDY_SOURCE_FILES: tuple[str, ...] = ("ct3m0214c.tif", "nj3m0214c.tif", "nys3m0214c.tif", "ri3m0214c.tif")
TARGET_CRS = "EPSG:9311"
# Comfortably above the observed max (~17.9m, NJ) -- guards against residual
# edge-of-tile compression artifacts, not a real physical cap.
MAX_PLAUSIBLE_DEPTH_M = 25.0


def sandy_union_bounds_9311(raw_dir: Path = DEFAULT_RAW_DIR) -> tuple[float, float, float, float]:
    """(west, south, east, north) in EPSG:9311 spanning all 4 source rasters.

    Header-only reads (no pixel data touched) -- cheap to call just to size a
    target grid before doing the real streaming reproject.
    """
    west = south = float("inf")
    east = north = float("-inf")
    for name in SANDY_SOURCE_FILES:
        with rasterio.open(raw_dir / name) as src:
            b = transform_bounds(src.crs, TARGET_CRS, *src.bounds)
        west, south = min(west, b[0]), min(south, b[1])
        east, north = max(east, b[2]), max(north, b[3])
    return west, south, east, north


def build_sandy_mosaic(
    resolution_m: float,
    *,
    raw_dir: Path = DEFAULT_RAW_DIR,
    source_files: tuple[str, ...] = SANDY_SOURCE_FILES,
) -> tuple[np.ndarray, Affine, str]:
    """Mosaic the 4 state-clipped Sandy depth grids onto one EPSG:9311 grid.

    Returns (array, transform, crs) -- array is float32 with NaN nodata.
    """
    source_paths = [raw_dir / name for name in source_files]
    for p in source_paths:
        if not p.exists():
            raise FileNotFoundError(p)

    west, south, east, north = sandy_union_bounds_9311(raw_dir)
    dst_width = max(1, math.ceil((east - west) / resolution_m))
    dst_height = max(1, math.ceil((north - south) / resolution_m))
    dst_transform = from_origin(west, north, resolution_m, resolution_m)
    print(
        f"Union grid ({TARGET_CRS} @ {resolution_m:.1f}m): {dst_width}x{dst_height} px "
        f"({dst_width * dst_height / 1e6:.1f}M pixels)"
    )

    sum_arr = np.zeros((dst_height, dst_width), dtype="float64")
    count_arr = np.zeros((dst_height, dst_width), dtype="int32")

    for p in source_paths:
        t0 = time.time()
        with rasterio.open(p) as src:
            tmp = np.full((dst_height, dst_width), np.nan, dtype="float32")
            reproject(
                source=rasterio.band(src, 1),
                destination=tmp,
                src_transform=src.transform,
                src_crs=src.crs,
                src_nodata=src.nodata,
                dst_transform=dst_transform,
                dst_crs=TARGET_CRS,
                dst_nodata=np.nan,
                resampling=Resampling.average,
            )
        valid = np.isfinite(tmp) & (tmp >= 0) & (tmp <= MAX_PLAUSIBLE_DEPTH_M)
        sum_arr[valid] += tmp[valid]
        count_arr[valid] += 1
        print(f"  {p.name}: {int(valid.sum()):,} valid px in {time.time() - t0:.1f}s")

    total_valid = int((count_arr > 0).sum())
    overlap = int((count_arr > 1).sum())
    if total_valid:
        print(
            f"Overlap: {overlap:,}/{total_valid:,} output px ({100 * overlap / total_valid:.2f}%) "
            "had valid data from >1 source -- averaged."
        )

    dst = np.where(count_arr > 0, sum_arr / np.maximum(count_arr, 1), np.nan).astype("float32")
    return dst, dst_transform, TARGET_CRS


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resolution", type=float, default=50.0, help="Target resolution in meters (EPSG:9311)")
    args = parser.parse_args()

    t0 = time.time()
    dst, dst_transform, dst_crs = build_sandy_mosaic(args.resolution, raw_dir=args.raw_dir)
    elapsed = time.time() - t0

    valid = dst[~np.isnan(dst)]
    print(f"Mosaicked in {elapsed:.1f}s. valid={valid.size}/{dst.size} ({100 * valid.size / dst.size:.1f}%)")
    if valid.size:
        print(
            f"depth (m): min={valid.min():.3f} max={valid.max():.3f} mean={valid.mean():.3f} "
            f"median={np.median(valid):.3f} p90={np.percentile(valid, 90):.3f} p99={np.percentile(valid, 99):.3f}"
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        args.output,
        "w",
        driver="GTiff",
        height=dst.shape[0],
        width=dst.shape[1],
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
