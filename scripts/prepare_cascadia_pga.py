#!/usr/bin/env python3
"""Convert the USGS Cascadia M9 ensemble ShakeMap's PGA grid (shake_result.hdf)
to a georeferenced, linear-g GeoTIFF ready for scripts/align_hazard_rasters.py.

Source: shake_result.hdf, ShakeMap 4.x format (HDF5 -- NOT the .flt/.hdr ESRI
BIL format prepare_shakemap_pga.py handles for Mineral/New Madrid). Event
cszm9ensemble_se, the MEDIAN (50th percentile) of an ensemble of 30 M9
rupture realizations (Frankel et al. 2018) for the Cascadia Subduction Zone
-- not a single deterministic ShakeMap.

Two things confirmed by direct inspection before use (2026-09-09, see
scripts/figures/_hazard_footprints_common.py's load_cascadia_pga_raw(), which
this script's core logic mirrors -- kept as a separate, standalone CLI here
rather than imported, since that module has matplotlib/geopandas import-time
side effects not wanted in a headless prep script):

1. UNITS: the array's own ``units`` attr says ln(g), and this is literal --
   exp(raw max 0.327) = 1.387, matching the file's own
   dictionaries/info.json ``max_grid`` value exactly. Unlike New Madrid's
   scenario download (which stores PERCENT g, linear), this Cascadia product
   uses the same ln(g) convention as Mineral's real-time ShakeMap.
2. GEOREFERENCING: grid geometry (xmin/xmax/ymin/ymax/dx/dy) and CRS
   (EPSG:4326 -- ShakeMap grids are always geographic) come directly from
   the dataset's own HDF5 attrs, not a separate .prj/.hdr file.

Also extracts SA(1.0) (confirmed present in this HDF, same grid geometry and
ln(g) units as PGA) as PGA's companion -- Sa(1.0s) is what
resiflow.hazards.hazus_bridge's bridge fragility needs; omitting it would
silently give this scenario's bridges a $0 cost, the same gap that was
deliberately fixed for Mineral/New Madrid on 2026-08-20 (see
docs/CONUS_MULTIHAZARD_METHODOLOGY.md's change log). Write the SA(1.0)
output to the sibling ``<hazard_subtype>_sa1p0/event_1.tif`` path
SiouxFallsMultihazardSource's sa1p0_companion expects (see
sioux_falls_multihazard.py).

Usage::

    # PGA:
    python scripts/prepare_cascadia_pga.py \\
        --input C:\\Users\\akothaw\\Desktop\\data\\Cascadia9_shake_result.hdf \\
        --output inputs/multihazard_raw/earthquake/cascadia_m9_scenario/pga_g.tif

    # SA(1.0) companion:
    python scripts/prepare_cascadia_pga.py \\
        --input C:\\Users\\akothaw\\Desktop\\data\\Cascadia9_shake_result.hdf \\
        --imt "SA(1.0)" \\
        --output inputs/multihazard_raw/earthquake/cascadia_m9_scenario/sa1p0_g.tif

Then align each (own-bounds -- Cascadia's PNW footprint has zero overlap
with the VA reference grid, same reasoning as New Madrid's central-US
footprint; the SA(1.0) companion must align onto the SAME grid as PGA, so
pass --reference pointing at PGA's own aligned output for it, not
--own-bounds again)::

    python scripts/align_hazard_rasters.py \\
        --input inputs/multihazard_raw/earthquake/cascadia_m9_scenario/pga_g.tif \\
        --own-bounds --resolution 50 \\
        --output inputs/multihazard_aligned/earthquake_cascadia_m9_scenario/event_1.tif

    python scripts/align_hazard_rasters.py \\
        --input inputs/multihazard_raw/earthquake/cascadia_m9_scenario/sa1p0_g.tif \\
        --reference inputs/multihazard_aligned/earthquake_cascadia_m9_scenario/event_1.tif \\
        --output inputs/multihazard_aligned/earthquake_cascadia_m9_scenario_sa1p0/event_1.tif
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import h5py
import numpy as np
import rasterio
from affine import Affine

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from resiflow.geo_runtime import configure_geo_runtime

# Must run before rasterio.open(..., crs=...) below -- confirmed on Hopper's
# `nird` conda env (2026-09-11) that without this, PROJ can't find proj.db
# and any CRS operation raises CPLE_AppDefinedError. Same fix
# align_hazard_rasters.py already relies on via rasterio_env() -- see
# docs/geo_projection_conus.md.
configure_geo_runtime()

ASSUMED_CRS = "EPSG:4326"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, required=True, help="Cascadia9_shake_result.hdf")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--imt", default="PGA", choices=["PGA", "SA(1.0)"],
        help="Which IMT dataset to extract -- both confirmed present in this HDF "
        "with the same grid geometry and ln(g) units (2026-09-11).",
    )
    parser.add_argument(
        "--dry-run-stats", action="store_true",
        help="Print raw (ln-g) and converted (linear-g) min/max and exit without writing output.",
    )
    args = parser.parse_args()

    with h5py.File(args.input, "r") as f:
        ds = f[f"arrays/imts/GREATER_OF_TWO_HORIZONTAL/{args.imt}/mean"]
        raw_ln_g = ds[()]
        xmin, xmax = float(ds.attrs["xmin"]), float(ds.attrs["xmax"])
        ymin, ymax = float(ds.attrs["ymin"]), float(ds.attrs["ymax"])
        dx, dy = float(ds.attrs["dx"]), float(ds.attrs["dy"])
        units = ds.attrs.get("units", "")

    print(f"Source units attr: {units!r} (expected 'ln(g)')")
    print(f"Raw ln(g) range: [{raw_ln_g.min():.4f}, {raw_ln_g.max():.4f}]")

    pga_g = np.exp(raw_ln_g).astype("float32")
    print(f"Converted linear-g range: [{np.nanmin(pga_g):.4f}, {np.nanmax(pga_g):.4f}]")

    if args.dry_run_stats:
        return 0

    # Standard north-up affine: row 0 at ymax, column 0 at xmin.
    transform = Affine(dx, 0.0, xmin, 0.0, -dy, ymax)

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

    print(f"Wrote {args.output} (CRS {ASSUMED_CRS}, {pga_g.shape[1]}x{pga_g.shape[0]} px)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
