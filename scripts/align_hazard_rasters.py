"""Align real hazard rasters to a common CRS/resolution/extent for comparison.

Extends what normalize_hazard_crs.py does (CRS reprojection only) with the
resolution + extent reconciliation needed to make hazards genuinely
"comparable": every output raster shares the same pixel grid (same origin,
resolution, width/height), derived from a --reference raster (default: the
existing VA toy flood raster, whose grid the rest of this project already
uses). See docs/VA_MULTIHAZARD_COMPARISON.md for the full ingestion story.

Usage:
    python scripts/align_hazard_rasters.py \
        --input inputs/va_multihazard_raw/flood/va_dcr_depth_01pct/Depth_01pct_va141_approx100m_clean.tif \
        --output inputs/va_multihazard_aligned/flood_surface/event_1.tif \
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
from rasterio.warp import Resampling, reproject

from resiflow.geo_runtime import CONUS_TARGET_CRS, canonical_crs, rasterio_env
from resiflow.utils import load_config


def _default_reference() -> Path:
    try:
        base_path = Path(load_config()["paths"]["soge_clusters"])
    except Exception:
        base_path = REPO_ROOT
    return base_path / "inputs" / "test_141node_50m" / "va_hazard_class50_141node_base.tif"


def reference_grid(reference_path: Path) -> dict:
    """Read the target CRS/resolution/bounds from a reference raster."""
    with rasterio.open(reference_path) as ref:
        return {
            "crs": ref.crs,
            "resolution": ref.res[0],
            "bounds": ref.bounds,
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
        help="Raster whose CRS/resolution/bounds define the common grid "
        "(default: the toy VA flood raster under config.json's soge_clusters path)",
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

    reference = args.reference or _default_reference()
    args.reference = reference
    if not reference.exists():
        raise SystemExit(f"Reference raster not found: {reference}")
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
