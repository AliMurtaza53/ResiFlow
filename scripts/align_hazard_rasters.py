"""Align real hazard rasters to a common CRS/resolution/extent for comparison.

Extends what normalize_hazard_crs.py does (CRS reprojection only) with the
resolution + extent reconciliation needed to make hazards genuinely
"comparable": every output raster shares the same pixel grid (same origin,
resolution, width/height), derived from either an explicit --reference
raster or --own-bounds (the input's own extent). There is no implicit
default grid -- earlier versions of this script silently fell back to a
small VA-sized reference raster when neither flag was passed, which quietly
clipped any hazard raster run without --own-bounds down to that bbox. See
docs/CONUS_MULTIHAZARD_METHODOLOGY.md for the full ingestion story.

Usage:
    python scripts/align_hazard_rasters.py \
        --input inputs/multihazard_raw/flood/va_dcr_depth_01pct/Depth_01pct_va141_approx100m_clean.tif \
        --output inputs/multihazard_aligned/flood_surface/event_1.tif \
        --unit-scale 0.3048   # feet -> meters
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import numpy as np
import rasterio
from rasterio.transform import Affine, from_origin
from rasterio.coords import BoundingBox
from rasterio.warp import Resampling, reproject, transform_bounds

from resiflow.geo_runtime import CONUS_TARGET_CRS, canonical_crs, rasterio_env


def reference_grid(reference_path: Path) -> dict:
    """Read the target CRS/resolution/bounds from a reference raster."""
    with rasterio.open(reference_path) as ref:
        return {
            "crs": ref.crs,
            "resolution": ref.res[0],
            "bounds": ref.bounds,
        }


def grid_from_source_bounds(input_path: Path, resolution: float) -> dict:
    """Derive a target grid directly from --input's own bounds, at
    ``resolution`` metres in the project's standard CRS.

    Use this for a hazard raster whose footprint is larger than whatever
    --reference raster is otherwise available -- aligning a wide-footprint
    event (e.g. a multi-state earthquake scenario) against a smaller
    reference grid would silently clip it down to that reference's own
    bounding box, discarding the whole point of using a bigger event. This
    is exactly what
    scripts/prepare_harvey_depths.py already had to do by hand for the
    Houston/Harris County Harvey case study (its own bounds -> EPSG:9311 at
    a chosen resolution) -- generalized here so future regional hazards
    don't need their own one-off copy of the same few lines. Harvey's script
    still does its own streaming reproject rather than using this (its
    source raster is ~84GB, too large for align_raster's full src.read());
    this path is for the common case where the source is small enough to
    read in one shot.
    """
    with rasterio.open(input_path) as src:
        target_crs = canonical_crs(CONUS_TARGET_CRS)
        bounds = transform_bounds(src.crs, target_crs, *src.bounds)

    return {
        "crs": target_crs,
        "resolution": resolution,
        "bounds": BoundingBox(*bounds),
    }


def align_raster(
    input_path: Path,
    output_path: Path,
    grid: dict,
    unit_scale: float = 1.0,
    resampling: Resampling = Resampling.bilinear,
    max_valid: float | None = None,
) -> dict:
    """Reproject + resample + clip a hazard raster onto ``grid``.

    ``grid`` must have ``crs``, ``resolution``, ``bounds`` (a rasterio
    BoundingBox) -- see ``reference_grid``. All rasters aligned against the
    same ``grid`` share an identical pixel grid (origin, resolution, shape),
    which is what makes them pixel-for-pixel comparable, not just
    same-CRS/same-resolution independently.

    ``max_valid`` (in source units, applied before ``unit_scale``) masks out
    values above it as nodata -- for known masking-boundary artifacts in a
    specific source raster (e.g. a handful of residual spike pixels sitting
    right at an upstream nodata cutoff), not a general-purpose outlier filter.
    """
    target_crs = canonical_crs(grid["crs"])
    res = grid["resolution"]
    b = grid["bounds"]
    dst_width = max(1, round((b.right - b.left) / res))
    dst_height = max(1, round((b.top - b.bottom) / res))
    dst_transform: Affine = from_origin(b.left, b.top, res, res)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio_env():
        with rasterio.open(input_path) as src:
            src_data = src.read(1, masked=True).astype("float64")
            if max_valid is not None:
                src_data = np.ma.masked_greater(src_data, max_valid)
            if unit_scale != 1.0:
                src_data = src_data * unit_scale
            dst_data = np.full((dst_height, dst_width), np.nan, dtype="float32")
            reproject(
                source=src_data.filled(np.nan).astype("float32"),
                destination=dst_data,
                src_transform=src.transform,
                src_crs=src.crs,
                src_nodata=np.nan,
                dst_transform=dst_transform,
                dst_crs=target_crs,
                dst_nodata=np.nan,
                resampling=resampling,
            )
            profile = {
                "driver": "GTiff",
                "height": dst_height,
                "width": dst_width,
                "count": 1,
                "dtype": "float32",
                "crs": target_crs,
                "transform": dst_transform,
                "nodata": np.nan,
                "compress": "lzw",
            }
            with rasterio.open(output_path, "w", **profile) as dst:
                dst.write(dst_data, 1)
            valid = dst_data[~np.isnan(dst_data)]
            return {
                "input": str(input_path),
                "output": str(output_path),
                "src_crs": str(src.crs),
                "dst_crs": target_crs.to_string(),
                "resolution_m": res,
                "shape": (dst_height, dst_width),
                "unit_scale": unit_scale,
                "valid_pixels": int(valid.size),
                "value_range": (float(valid.min()), float(valid.max())) if valid.size else None,
            }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--reference",
        type=Path,
        default=None,
        help="Raster whose CRS/resolution/bounds define the common grid. "
        "Required unless --own-bounds is passed instead -- there is no "
        "implicit default reference raster.",
    )
    parser.add_argument(
        "--own-bounds",
        action="store_true",
        help="Derive the target grid from --input's own bounds instead of a "
        "--reference raster -- use for a hazard whose footprint is larger "
        "than any available reference grid, so it isn't silently clipped "
        "down to that grid's own bounds. Mutually exclusive with "
        "--reference. Requires --resolution.",
    )
    parser.add_argument(
        "--resolution",
        type=float,
        default=None,
        help="Target resolution in metres, only used with --own-bounds "
        "(match whatever resolution your other aligned hazards use, for "
        "cross-event comparability, unless there's a specific reason not to).",
    )
    parser.add_argument(
        "--unit-scale",
        type=float,
        default=1.0,
        help="Multiply source values by this before writing (e.g. 0.3048 for feet->meters)",
    )
    parser.add_argument(
        "--nearest",
        action="store_true",
        help="Use nearest-neighbor instead of bilinear (e.g. for categorical/class rasters)",
    )
    parser.add_argument(
        "--max-valid",
        type=float,
        default=None,
        help="Mask values above this (in source units, before --unit-scale) as "
        "nodata -- for known masking-boundary artifacts in a specific source raster.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", force=True)

    if args.own_bounds:
        if args.reference is not None:
            raise SystemExit("--own-bounds and --reference are mutually exclusive")
        if args.resolution is None:
            raise SystemExit("--own-bounds requires --resolution")
        grid = grid_from_source_bounds(args.input, args.resolution)
        logging.info(
            "Target grid from %s's own bounds: crs=%s, resolution=%sm, bounds=%s",
            args.input,
            grid["crs"],
            grid["resolution"],
            grid["bounds"],
        )
    else:
        if args.reference is None:
            raise SystemExit(
                "Pass --reference <raster> (to align onto an existing grid) or "
                "--own-bounds --resolution <metres> (to derive the grid from "
                "--input itself) -- there is no implicit default grid."
            )
        if not args.reference.exists():
            raise SystemExit(f"Reference raster not found: {args.reference}")
        grid = reference_grid(args.reference)
        logging.info(
            "Target grid from %s: crs=%s, resolution=%sm, bounds=%s",
            args.reference,
            grid["crs"],
            grid["resolution"],
            grid["bounds"],
        )

    result = align_raster(
        args.input,
        args.output,
        grid,
        unit_scale=args.unit_scale,
        resampling=Resampling.nearest if args.nearest else Resampling.bilinear,
        max_valid=args.max_valid,
    )
    logging.info(
        "%s -> %s | shape=%s | valid_pixels=%d | value_range=%s",
        result["input"],
        result["output"],
        result["shape"],
        result["valid_pixels"],
        result["value_range"],
    )


if __name__ == "__main__":
    main()
