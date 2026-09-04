#!/usr/bin/env python3
"""Compute a HAZUS-style landslide PGD (permanent ground displacement) raster.

Combines an ALIGNED susceptibility class raster and an ALIGNED PGA raster
(both already reprojected/resampled onto the common grid via
scripts/align_hazard_rasters.py) into landslide_pgd_mm.tif -- mm of
displacement, the same unit fragility/landslide_categorical.py's
_MAJOR_MM/_MINOR_MM thresholds expect. See
src/resiflow/hazards/landslide_pgd.py for the HAZUS methodology
(Equations 4-14/4-15, Tables 4-16, digitized Figure 4-13) and its documented
modeling choices/limitations.

The susceptibility raster's integer class values (default assumed 0=None..
10=X, matching Table 4-16's ordering) are NOT yet confirmed against the real
n10_susc raster's actual class scheme -- run with --dry-run-stats first and
compare the reported class histogram against USGS's n10 model documentation
before trusting output. Use --class-map to remap if the raster uses a
different numbering.

Example::

    python scripts/compute_landslide_pgd.py \
        --susceptibility inputs/va_multihazard_aligned/landslide_susceptibility/event_1.tif \
        --pga inputs/va_multihazard_aligned/earthquake/event_1.tif \
        --output inputs/va_multihazard_aligned/landslide/event_1.tif \
        --magnitude 5.8
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

import numpy as np
import rasterio

from resiflow.hazards.landslide_pgd import bin_fractional_susceptibility_to_class, expected_pgd_mm


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--susceptibility", type=Path, required=True, help="Aligned susceptibility class raster")
    parser.add_argument("--pga", type=Path, required=True, help="Aligned PGA raster (g)")
    parser.add_argument("--output", type=Path, required=True, help="Output landslide_pgd_mm.tif path")
    parser.add_argument(
        "--magnitude",
        type=float,
        default=None,
        help="Scenario moment magnitude M for Equation 4-15's cycle count -- "
        "HAZUS's Newmark method is per-scenario-earthquake, not tied to the "
        "NSHM PGA hazard curve, so this must be chosen explicitly. Required "
        "unless --dry-run-stats.",
    )
    parser.add_argument(
        "--class-map",
        type=Path,
        default=None,
        help="Optional JSON file mapping raw raster values (as strings) to "
        "integer susceptibility classes 0(None)-10(X). Default: assume the "
        "raster is already 0-10.",
    )
    parser.add_argument(
        "--susceptibility-max-count",
        type=float,
        default=None,
        help="If the susceptibility raster is a continuous count (e.g. USGS "
        "n10's 0-81 'susceptible 10m sub-cells per 90m cell'), pass its max "
        "value here to equal-width-bin it into None/I-X classes -- see "
        "landslide_pgd.bin_fractional_susceptibility_to_class. Mutually "
        "exclusive with --class-map.",
    )
    parser.add_argument("--dry-run-stats", action="store_true", help="Print input class/PGA histograms and exit without writing output")
    args = parser.parse_args()
    if args.magnitude is None and not args.dry_run_stats:
        parser.error("--magnitude is required unless --dry-run-stats")

    with rasterio.open(args.susceptibility) as susc_ds, rasterio.open(args.pga) as pga_ds:
        if susc_ds.shape != pga_ds.shape or susc_ds.transform != pga_ds.transform:
            raise SystemExit(
                "Susceptibility and PGA rasters are not on the same grid -- "
                "align both with scripts/align_hazard_rasters.py against the same --reference first."
            )
        susc = susc_ds.read(1, masked=True).astype("float64").filled(np.nan)
        pga = pga_ds.read(1, masked=True).astype("float64").filled(np.nan)
        profile = pga_ds.profile

    if args.class_map is not None and args.susceptibility_max_count is not None:
        raise SystemExit("--class-map and --susceptibility-max-count are mutually exclusive")

    if args.class_map is not None:
        raw_to_class = {float(k): int(v) for k, v in json.loads(args.class_map.read_text()).items()}
        remapped = np.full_like(susc, np.nan)
        for raw_value, class_index in raw_to_class.items():
            remapped[np.isclose(susc, raw_value, equal_nan=False)] = class_index
        susc = remapped
    elif args.susceptibility_max_count is not None:
        valid = ~np.isnan(susc)
        binned = np.full_like(susc, np.nan)
        binned[valid] = bin_fractional_susceptibility_to_class(susc[valid], args.susceptibility_max_count)
        susc = binned

    if args.dry_run_stats:
        valid_susc = susc[~np.isnan(susc)]
        valid_pga = pga[~np.isnan(pga)]
        print(f"Susceptibility: n_valid={valid_susc.size}, unique_values={np.unique(valid_susc)[:20]}")
        print(f"PGA (g): n_valid={valid_pga.size}, min={valid_pga.min() if valid_pga.size else 'n/a'}, "
              f"max={valid_pga.max() if valid_pga.size else 'n/a'}")
        return 0

    pgd_mm = expected_pgd_mm(susc, pga, magnitude=args.magnitude)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    out_profile = dict(profile)
    out_profile.update(dtype="float32", nodata=np.nan, compress="lzw")
    with rasterio.open(args.output, "w", **out_profile) as dst:
        dst.write(pgd_mm, 1)

    valid = pgd_mm[~np.isnan(pgd_mm)]
    nonzero = valid[valid > 0]
    print(
        f"Wrote {args.output} | shape={pgd_mm.shape} | valid_pixels={valid.size} | "
        f"nonzero_pixels={nonzero.size} | pgd_mm_range="
        f"{(float(nonzero.min()), float(nonzero.max())) if nonzero.size else 'n/a'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
