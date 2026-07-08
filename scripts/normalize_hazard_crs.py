"""Normalize hazard GeoTIFF CRS metadata for CONUS workflows."""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import rasterio
from rasterio.warp import Resampling, calculate_default_transform, reproject

from resiflow.geo_runtime import (
    CONUS_TARGET_CRS,
    canonical_crs,
    configure_geo_runtime,
    crs_equivalent,
    rasterio_env,
)


def normalize_raster(
    input_path: Path,
    output_path: Path,
    target_crs: str = CONUS_TARGET_CRS,
    metadata_only: bool = False,
) -> dict:
    target = canonical_crs(target_crs)
    with rasterio_env():
        with rasterio.open(input_path) as src:
            before = str(src.crs) if src.crs is not None else "None"
            if crs_equivalent(src.crs, target) and metadata_only:
                profile = src.profile.copy()
                profile["crs"] = target
                data = src.read()
                with rasterio.open(output_path, "w", **profile) as dst:
                    dst.write(data)
                    dst.update_tags(**src.tags())
                after = target.to_string()
                return {
                    "input": str(input_path),
                    "output": str(output_path),
                    "before_crs": before,
                    "after_crs": after,
                    "warped": False,
                    "metadata_only": True,
                }

            if crs_equivalent(src.crs, target) and not metadata_only:
                profile = src.profile.copy()
                profile["crs"] = target
                data = src.read()
                with rasterio.open(output_path, "w", **profile) as dst:
                    dst.write(data)
                    dst.update_tags(**src.tags())
                return {
                    "input": str(input_path),
                    "output": str(output_path),
                    "before_crs": before,
                    "after_crs": target.to_string(),
                    "warped": False,
                    "metadata_only": True,
                }

            dst_transform, dst_width, dst_height = calculate_default_transform(
                src.crs,
                target,
                src.width,
                src.height,
                *src.bounds,
            )
            profile = src.profile.copy()
            profile.update(
                crs=target,
                transform=dst_transform,
                width=dst_width,
                height=dst_height,
            )
            with rasterio.open(output_path, "w", **profile) as dst:
                for band in range(1, src.count + 1):
                    reproject(
                        source=rasterio.band(src, band),
                        destination=rasterio.band(dst, band),
                        src_transform=src.transform,
                        src_crs=src.crs,
                        dst_transform=dst_transform,
                        dst_crs=target,
                        resampling=Resampling.bilinear,
                    )
            return {
                "input": str(input_path),
                "output": str(output_path),
                "before_crs": before,
                "after_crs": target.to_string(),
                "warped": True,
                "metadata_only": False,
            }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, action="append", help="Input GeoTIFF path")
    parser.add_argument("--input-dir", type=Path, help="Directory of GeoTIFF files")
    parser.add_argument("--output-dir", type=Path, help="Write normalized copies here")
    parser.add_argument("--target-crs", default=CONUS_TARGET_CRS)
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="Rewrite files in place (creates .bak backup first)",
    )
    parser.add_argument(
        "--force-warp",
        action="store_true",
        help="Always warp even when CRS aliases are equivalent",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    configure_geo_runtime()

    inputs: list[Path] = list(args.input or [])
    if args.input_dir:
        inputs.extend(sorted(args.input_dir.glob("*.tif")))
        inputs.extend(sorted(args.input_dir.glob("*.tiff")))

    if not inputs:
        raise SystemExit("Provide --input and/or --input-dir")

    for input_path in inputs:
        if args.in_place:
            backup = input_path.with_suffix(input_path.suffix + ".bak")
            if not backup.exists():
                shutil.copy2(input_path, backup)
            output_path = input_path
        elif args.output_dir:
            args.output_dir.mkdir(parents=True, exist_ok=True)
            output_path = args.output_dir / input_path.name
        else:
            output_path = input_path.with_name(f"{input_path.stem}_epsg2163{input_path.suffix}")

        result = normalize_raster(
            input_path=input_path,
            output_path=output_path,
            target_crs=args.target_crs,
            metadata_only=not args.force_warp,
        )
        logging.info(
            "%s -> %s | before=%s | after=%s | warped=%s",
            result["input"],
            result["output"],
            result["before_crs"],
            result["after_crs"],
            result["warped"],
        )


if __name__ == "__main__":
    main()
