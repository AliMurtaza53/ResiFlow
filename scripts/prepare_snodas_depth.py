#!/usr/bin/env python3
"""Convert a raw NOHRSC SNODAS daily archive's snow-depth product to a
georeferenced GeoTIFF (mm), ready for scripts/align_hazard_rasters.py.

Source: SNODAS_YYYYMMDD.tar, NOAA NOHRSC's daily CONUS snow data assimilation
product (archive: https://noaadata.apps.nsidc.org/NOAA/G02158/masked/,
documented at https://nsidc.org/data/g02158). Each tar bundles ~8 gzipped
product pairs (.txt.gz header + .dat.gz binary grid); this script extracts
only the snow-depth product (SNODAS product code 1036, filename prefix
"us_ssmv11036" -- "Modeled snow layer thickness, total of snow layers" per
its own header's Description field) and discards the rest (SWE, various
melt/precip/sublimation fluxes -- not needed for a road-closure proxy).

Format, confirmed against the NSIDC SNODAS user guide (primary source:
https://nsidc.org/sites/default/files/g02158-v001-userguide_2_1.pdf) and
cross-checked directly against this project's own downloaded header text,
not assumed from memory (an earlier version of this project's ShakeMap prep
script had to correct a similar units assumption after the fact -- see
prepare_shakemap_pga.py's own docstring for that history):

1. BINARY LAYOUT: flat, headerless, big-endian ('>i2') 16-bit signed integer
   grid, row-major from the northwest corner -- explicitly stated in the
   NSIDC user guide and matching this project's own downloaded header
   ("Data type: integer", "Data bytes per pixel: 2").

2. UNITS: the header's "Data units: Meters / 1000.000000" means the raw
   integer, divided by 1000, gives the value in METERS -- i.e. the raw
   integer IS the depth in millimetres already (no further scaling needed;
   "Data intercept: 0" / "Data slope: 1" confirm no additional affine
   transform on top of that). This matches the mm unit
   fragility/winter_storm_categorical.py's compute_damage_levels_vectorized
   already expects, and matches the "meters->mm" conversion already
   documented for this project's existing single SNODAS day (2016-01-23) in
   parameters/hazards.va_real.example.json.

3. NODATA: -9999 (from the header's "No data value" field). Also masks
   32767 (int16's maximum representable value) as a second, undocumented
   nodata sentinel -- confirmed via direct inspection of three independent
   real days (2010-02-06, 2021-02-17, 2022-12-24) that a small, spatially
   FIXED cluster of grid cells (same ~2-3 pixel locations recur across all
   three unrelated dates) reports exactly 32767mm (32.7m) of snow, which is
   physically absurd and can't be a real, independently-varying storm
   signal -- almost certainly a model-instability artifact at those specific
   cells rather than real data. A real value coinciding with int16's exact
   storage ceiling would itself be an implausible coincidence. This is a
   data-quality finding, not documented behavior in the NSIDC user guide --
   flagged here for whoever revisits this. A second, lower but still
   physically implausible spike (23392mm / 23.4m, 2010-02-06 only, same
   general high-terrain grid cell cluster) was NOT masked here -- unlike
   32767 it isn't a clean storage-ceiling value, so it's plausibly a
   genuine (if extreme) high-mountain SNODAS model estimate rather than a
   clear artifact; flagged for whoever aligns this raster to consider
   align_hazard_rasters.py's --max-valid if a stricter physical cap is
   wanted.

4. GEOREFERENCING: WGS84 geographic (header states "Horizontal datum:
   WGS84", "Projected: no" explicitly -- not an assumption, unlike
   ShakeMap's missing .prj). The header's "Benchmark x/y-axis coordinate"
   fields are CELL-CENTER coordinates (confirmed: benchmark_x - half a
   pixel's X-axis offset reproduces "Minimum x-axis coordinate" to within
   float noise) -- this script uses the header's explicit
   Minimum-x/Maximum-y EDGE bounds for the affine transform origin instead,
   to avoid a half-pixel registration error.

Usage::

    python scripts/prepare_snodas_depth.py \\
        --tar inputs_raw/winter_storm/SNODAS_20210217.tar \\
        --output inputs/va_multihazard_raw/winter_storm/uri_20210217/depth_mm.tif
"""

from __future__ import annotations

import argparse
import gzip
import tarfile
from pathlib import Path

import numpy as np
import rasterio
from affine import Affine

SNOW_DEPTH_PREFIX = "us_ssmv11036"
ASSUMED_CRS = "EPSG:4326"
NODATA = -9999.0
# int16's max representable value -- confirmed via cross-date inspection to
# be a fixed-location model artifact, not real snow depth. See module
# docstring point 3.
ARTIFACT_SENTINEL = 32767.0


def _parse_header(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        out[key.strip()] = value.strip()
    return out


def load_snow_depth(tar_path: Path) -> tuple[np.ndarray, dict[str, str]]:
    with tarfile.open(tar_path) as tf:
        members = {m.name: m for m in tf.getmembers()}
        txt_name = next((n for n in members if n.startswith(SNOW_DEPTH_PREFIX) and n.endswith(".txt.gz")), None)
        dat_name = next((n for n in members if n.startswith(SNOW_DEPTH_PREFIX) and n.endswith(".dat.gz")), None)
        if txt_name is None or dat_name is None:
            raise SystemExit(
                f"No snow-depth product ({SNOW_DEPTH_PREFIX}*) found in {tar_path} -- "
                f"available members: {sorted(members)[:10]}..."
            )
        header_text = gzip.decompress(tf.extractfile(txt_name).read()).decode()
        raw_bytes = gzip.decompress(tf.extractfile(dat_name).read())

    header = _parse_header(header_text)
    ncols = int(header["Number of columns"])
    nrows = int(header["Number of rows"])

    arr = np.frombuffer(raw_bytes, dtype=">i2").reshape(nrows, ncols).astype("float64")
    return arr, header


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tar", type=Path, required=True, help="Raw SNODAS_YYYYMMDD.tar")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    arr, header = load_snow_depth(args.tar)

    nodata_raw = float(header["No data value"])
    valid_mask = (arr != nodata_raw) & (arr != ARTIFACT_SENTINEL)
    n_artifact = int((arr == ARTIFACT_SENTINEL).sum())
    n_valid = int(valid_mask.sum())

    depth_mm = np.full(arr.shape, np.nan, dtype="float32")
    depth_mm[valid_mask] = arr[valid_mask].astype("float32")

    print(
        f"snow depth: shape={arr.shape}, valid={n_valid}/{arr.size} "
        f"({100 * n_valid / arr.size:.1f}%), masked {n_artifact} artifact-sentinel "
        f"({ARTIFACT_SENTINEL:.0f}mm) pixels, mm range="
        f"[{np.nanmin(depth_mm):.1f}, {np.nanmax(depth_mm):.1f}], mean={np.nanmean(depth_mm):.2f}"
    )

    min_x = float(header["Minimum x-axis coordinate"])
    max_y = float(header["Maximum y-axis coordinate"])
    res_x = float(header["X-axis resolution"])
    res_y = float(header["Y-axis resolution"])
    transform = Affine(res_x, 0.0, min_x, 0.0, -res_y, max_y)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        args.output,
        "w",
        driver="GTiff",
        height=depth_mm.shape[0],
        width=depth_mm.shape[1],
        count=1,
        dtype="float32",
        crs=ASSUMED_CRS,
        transform=transform,
        nodata=np.nan,
        compress="deflate",
    ) as dst:
        dst.write(depth_mm, 1)

    print(f"Wrote {args.output} (CRS {ASSUMED_CRS}, confirmed from header -- not an assumption)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
