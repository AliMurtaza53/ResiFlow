#!/usr/bin/env python3
"""Convert a USGS ShakeMap PGA grid (real event or scenario) to a
georeferenced, linear-g GeoTIFF ready for scripts/align_hazard_rasters.py.

Originally written for the real 2011 Mineral, VA M5.8 event
(M5_8_ShakeMap_raster.zip); generalized 2026-08-20 for the USGS Earthquake
Scenarios catalog (e.g. the BSSC2014 New Madrid M7.5 scenario), which turns
out to differ in two real ways, not just packaging -- confirmed by direct
inspection, not assumed by analogy with the Mineral file:

1. HEADER CONVENTION: Mineral's .hdr uses ULXMAP/ULYMAP/XDIM/YDIM (an
   upper-left-corner-origin ESRI BIL header, from USGS's real-time ShakeMap
   system). The New Madrid scenario's .hdr uses NCOLS/NROWS/XLLCORNER/
   YLLCORNER/CELLSIZE (a lower-left-corner-origin ESRI ASCII-grid-style
   header, from the separate Earthquake Scenarios/BSSC2014 system) --
   confirmed by reading the actual file, not guessed. Both are handled here
   by detecting which keys are present.

2. UNITS: Mineral's grid stores PGA as ln(g) (confirmed via shakelib's own
   docs and the raw values being uniformly negative -- see the exp()
   transform below). The New Madrid scenario's grid instead stores PGA as
   PERCENT g, LINEAR -- confirmed by directly inspecting the raw floats
   (range ~0.4 to ~131, no negative values; 131 as ln(g) would be
   nonsensical, but 131%g = 1.31g is a physically sane near-fault peak
   acceleration for a M7.5 event). Getting this wrong silently would be a
   ~100x-scale bug with no error, not a crash -- so --units is a REQUIRED,
   no-default argument. Pick the wrong one and every fragility threshold
   fed by this raster is wrong. When in doubt, dump the raw min/max first
   (--dry-run-stats) and sanity-check by the same reasoning used above
   before choosing.

3. GEOREFERENCING: the New Madrid scenario download includes a real
   shape/pga.prj (GCS_WGS_1984) confirming EPSG:4326 directly -- unlike
   Mineral, which had no .prj and required assuming ShakeMap's standard
   product CRS. Both happen to resolve to the same CRS here, but this
   script still treats it as an assumption (ASSUMED_CRS) rather than
   something read from an arbitrary source .prj, since parsing arbitrary
   WKT robustly is out of scope -- if a future source's real CRS differs,
   this needs to be caught by hand, same as Mineral's case was.

MMI is NOT log- or percent-transformed in ShakeMap products (confirmed by
its raw values already sitting on MMI's normal ~1-10 scale in both sources)
-- do not apply --units to it if it's ever converted here; pass --units g.

Usage::

    # Real event (zip of .flt/.hdr pairs, ln(g) units):
    python scripts/prepare_shakemap_pga.py \\
        --zip inputs/va_multihazard_raw/earthquake/mineral_shakemap/M5_8_ShakeMap_raster.zip \\
        --layer pga_mean --units ln_g \\
        --output inputs/va_multihazard_raw/earthquake/mineral_shakemap/pga_g.tif

    # Scenario event (already-extracted dir of .fit/.hdr pairs, percent-g units):
    python scripts/prepare_shakemap_pga.py \\
        --dir inputs/va_multihazard_raw/earthquake/new_madrid_scenario/raster \\
        --layer pga --units pct_g \\
        --output inputs/va_multihazard_raw/earthquake/new_madrid_scenario/pga_g.tif
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


def _read_bytes(source, name: str) -> bytes:
    """source is either a zipfile.ZipFile or a directory Path."""
    if isinstance(source, zipfile.ZipFile):
        return source.read(name)
    return (source / name).read_bytes()


def _find_data_name(source, stem: str) -> str:
    for ext in (".flt", ".fit"):
        name = f"{stem}{ext}"
        if isinstance(source, zipfile.ZipFile):
            if name in source.namelist():
                return name
        elif (source / name).exists():
            return name
    raise SystemExit(f"No {stem}.flt or {stem}.fit found in the source")


def load_grid_layer(source, stem: str) -> tuple[np.ndarray, dict[str, float]]:
    hdr = parse_hdr(_read_bytes(source, f"{stem}.hdr").decode())
    nrows, ncols = int(hdr["NROWS"]), int(hdr["NCOLS"])
    data_name = _find_data_name(source, stem)
    arr = np.frombuffer(_read_bytes(source, data_name), dtype="<f4").reshape(nrows, ncols).copy()
    return arr, hdr


def build_transform(hdr: dict[str, float]) -> Affine:
    if {"ULXMAP", "ULYMAP", "XDIM", "YDIM"} <= hdr.keys():
        # Upper-left-corner-origin header (Mineral / real-time ShakeMap convention).
        return Affine(hdr["XDIM"], 0.0, hdr["ULXMAP"], 0.0, -hdr["YDIM"], hdr["ULYMAP"])
    if {"XLLCORNER", "YLLCORNER", "CELLSIZE", "NROWS"} <= hdr.keys():
        # Lower-left-corner-origin header (Earthquake Scenarios / BSSC2014 convention).
        # Recover the top edge from the bottom edge + grid height, since a
        # north-up raster's affine transform needs the top-left corner.
        cellsize = hdr["CELLSIZE"]
        top_y = hdr["YLLCORNER"] + hdr["NROWS"] * cellsize
        return Affine(cellsize, 0.0, hdr["XLLCORNER"], 0.0, -cellsize, top_y)
    raise SystemExit(
        f"Unrecognized .hdr key set: {sorted(hdr.keys())} -- neither the "
        "ULXMAP/ULYMAP/XDIM/YDIM nor XLLCORNER/YLLCORNER/CELLSIZE/NROWS "
        "convention matched. Add a case for this header format rather than "
        "guessing the transform."
    )


def convert_to_linear_g(arr: np.ndarray, valid_mask: np.ndarray, units: str) -> np.ndarray:
    out = np.full(arr.shape, np.nan, dtype="float32")
    if units == "ln_g":
        out[valid_mask] = np.exp(arr[valid_mask].astype("float64")).astype("float32")
    elif units == "pct_g":
        out[valid_mask] = (arr[valid_mask].astype("float64") / 100.0).astype("float32")
    elif units == "g":
        out[valid_mask] = arr[valid_mask].astype("float32")
    else:  # pragma: no cover -- argparse choices already restrict this
        raise ValueError(units)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--zip", type=Path, help="Zip of .flt/.fit + .hdr pairs")
    source_group.add_argument("--dir", type=Path, help="Already-extracted directory of .flt/.fit + .hdr pairs")
    parser.add_argument("--layer", default="pga", help="Grid stem to convert (e.g. 'pga', 'pga_mean')")
    parser.add_argument(
        "--units",
        required=True,
        choices=["ln_g", "pct_g", "g"],
        help="Raw grid units: ln_g (natural-log g, real-time ShakeMap convention), "
        "pct_g (percent g, linear -- Earthquake Scenarios convention), or g "
        "(already linear g -- no transform). REQUIRED, no default: a wrong "
        "guess here silently scales every downstream value, it doesn't crash.",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--dry-run-stats",
        action="store_true",
        help="Print raw (untransformed) min/max/sample values and exit -- use this "
        "first to sanity-check which --units is right before committing to a run.",
    )
    args = parser.parse_args()

    if args.zip is not None:
        with zipfile.ZipFile(args.zip) as zf:
            arr, hdr = load_grid_layer(zf, args.layer)
    else:
        arr, hdr = load_grid_layer(args.dir, args.layer)

    nodata_raw = hdr.get("NODATA")
    valid_mask = arr != nodata_raw if nodata_raw is not None else np.ones(arr.shape, dtype=bool)
    n_valid = int(valid_mask.sum())
    raw_valid = arr[valid_mask]

    if args.dry_run_stats:
        print(
            f"{args.layer}: shape={arr.shape}, valid={n_valid}/{arr.size} "
            f"({100 * n_valid / arr.size:.1f}%), raw range="
            f"[{raw_valid.min():.4f}, {raw_valid.max():.4f}], sample={raw_valid[:5]}"
        )
        print(
            "Sanity check: ln(g) grids are uniformly negative (g < 1 everywhere is "
            "typical); pct_g grids are positive, often > 1 near-fault; g grids are "
            "positive and small (< ~2 almost everywhere)."
        )
        return 0

    print(f"{args.layer}: shape={arr.shape}, valid={n_valid}/{arr.size} "
          f"({100 * n_valid / arr.size:.1f}%), raw ({args.units}) range="
          f"[{raw_valid.min():.4f}, {raw_valid.max():.4f}]")

    pga_g = convert_to_linear_g(arr, valid_mask, args.units)
    print(f"{args.layer} converted to linear g: range="
          f"[{np.nanmin(pga_g):.4f}, {np.nanmax(pga_g):.4f}], "
          f"mean={np.nanmean(pga_g):.4f}")

    transform = build_transform(hdr)

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

    print(f"Wrote {args.output} (CRS assumed {ASSUMED_CRS})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
