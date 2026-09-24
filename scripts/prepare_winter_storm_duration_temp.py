#!/usr/bin/env python3
"""Build real (if approximate) duration_hours and air_temp_F companion
rasters for one winter-storm event, closing T32's Track B Step 2 blocker
(``parameters/tables/T32_winter_storm_direct_cost_function.csv``: "needs
duration_hours and air_temp_F per event/link -- the pipeline currently only
carries winter_storm_max_mm").

Two real, freely-downloadable sources, NOT the ideal ones T32's own header
cites (NOHRSC's 6-hr National Gridded Snowfall Analysis' historical archive
for these specific past dates wasn't readily reachable within scope -- see
docs/HAZARD_TABLE_INTEGRATION_RUNBOOK.md Track B):

1. **duration_hours** -- derived from THREE consecutive days of NOHRSC
   SNODAS daily snow-DEPTH grids (peak day +/- 1), the same product
   scripts/prepare_snodas_depth.py already uses for winter_storm_max_mm
   (https://noaadata.apps.nsidc.org/NOAA/G02158/masked/). Depth is a state
   variable (total snowpack), not a snowfall flux, so "duration" here is a
   coarse, 24-hour-granularity proxy: a day counts as "actively snowing" if
   depth increased by more than ``--increase-threshold-mm`` versus the prior
   day; duration_hours = 24 * (count of qualifying day-over-day increases
   among the two transitions in the 3-day window). This will UNDER-count a
   storm that starts and ends within one calendar day and OVER-count one
   where snow keeps compacting/redistributing across days without new
   snowfall -- a real, documented approximation, not the ideal source.

2. **air_temp_F** -- PRISM daily minimum temperature (tmin), 4km CONUS,
   downloaded from PRISM's public web service
   (https://services.nacse.org/prism/data/get/us/4km/tmin/<YYYYMMDD>, no
   auth required), for the event's peak day. A real, per-pixel value, but
   the day's MINIMUM rather than a storm-hour-specific reading -- T32's own
   header lists PRISM as one of its cited temperature sources, so this is
   within the table's own intended input class, just a specific choice
   (tmin, not tmean) documented here. Converted from the source's native
   Celsius to the Fahrenheit T32's formula expects.

Usage::

    python scripts/prepare_winter_storm_duration_temp.py \\
        --snodas-tar-before inputs_raw/SNODAS_20160122.tar \\
        --snodas-tar-peak   inputs_raw/SNODAS_20160123.tar \\
        --snodas-tar-after  inputs_raw/SNODAS_20160124.tar \\
        --prism-tmin-zip inputs_raw/prism_tmin_20160123.zip \\
        --output-dir inputs/multihazard_aligned/winter_storm_duration_temp/winter_storm
"""

from __future__ import annotations

import argparse
import gzip
import tarfile
import zipfile
from pathlib import Path

import numpy as np
import rasterio
from affine import Affine

SNOW_DEPTH_PREFIX = "us_ssmv11036"
ASSUMED_CRS = "EPSG:4326"
NODATA = -9999.0
ARTIFACT_SENTINEL = 32767.0
DEFAULT_INCREASE_THRESHOLD_MM = 10.0


def _parse_header(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        out[key.strip()] = value.strip()
    return out


def _load_snodas_depth_mm(tar_path: Path) -> tuple[np.ndarray, dict[str, str]]:
    """Same parsing as scripts/prepare_snodas_depth.py's load_snow_depth --
    see that script's docstring for the binary-layout/units/nodata citations
    (not repeated here to avoid drift between two copies going stale
    differently; this one intentionally stays a minimal, self-contained copy
    per this repo's existing one-off-prep-script convention)."""
    with tarfile.open(tar_path) as tf:
        members = {m.name: m for m in tf.getmembers()}
        txt_name = next((n for n in members if n.startswith(SNOW_DEPTH_PREFIX) and n.endswith(".txt.gz")), None)
        dat_name = next((n for n in members if n.startswith(SNOW_DEPTH_PREFIX) and n.endswith(".dat.gz")), None)
        if txt_name is None or dat_name is None:
            raise SystemExit(f"No snow-depth product ({SNOW_DEPTH_PREFIX}*) found in {tar_path}")
        header_text = gzip.decompress(tf.extractfile(txt_name).read()).decode()
        raw_bytes = gzip.decompress(tf.extractfile(dat_name).read())

    header = _parse_header(header_text)
    ncols = int(header["Number of columns"])
    nrows = int(header["Number of rows"])
    arr = np.frombuffer(raw_bytes, dtype=">i2").reshape(nrows, ncols).astype("float64")

    nodata_raw = float(header["No data value"])
    valid_mask = (arr != nodata_raw) & (arr != ARTIFACT_SENTINEL)
    depth_mm = np.full(arr.shape, np.nan, dtype="float32")
    depth_mm[valid_mask] = arr[valid_mask].astype("float32")
    return depth_mm, header


def _snodas_transform(header: dict[str, str]) -> Affine:
    min_x = float(header["Minimum x-axis coordinate"])
    max_y = float(header["Maximum y-axis coordinate"])
    res_x = float(header["X-axis resolution"])
    res_y = float(header["Y-axis resolution"])
    return Affine(res_x, 0.0, min_x, 0.0, -res_y, max_y)


def _write_geotiff(path: Path, array: np.ndarray, *, crs: str, transform: Affine, nodata: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path, "w", driver="GTiff", height=array.shape[0], width=array.shape[1], count=1,
        dtype="float32", crs=crs, transform=transform, nodata=nodata, compress="deflate",
    ) as dst:
        dst.write(array.astype("float32"), 1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--snodas-tar-before", type=Path, required=True)
    parser.add_argument("--snodas-tar-peak", type=Path, required=True)
    parser.add_argument("--snodas-tar-after", type=Path, required=True)
    parser.add_argument("--prism-tmin-zip", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--increase-threshold-mm", type=float, default=DEFAULT_INCREASE_THRESHOLD_MM)
    args = parser.parse_args()

    depth_before, header_before = _load_snodas_depth_mm(args.snodas_tar_before)
    depth_peak, header_peak = _load_snodas_depth_mm(args.snodas_tar_peak)
    depth_after, header_after = _load_snodas_depth_mm(args.snodas_tar_after)
    if depth_before.shape != depth_peak.shape or depth_peak.shape != depth_after.shape:
        raise SystemExit("SNODAS grids for the 3 days have mismatched shapes -- cannot difference them")

    delta_in = depth_peak - depth_before
    delta_out = depth_after - depth_peak
    active_in = np.nan_to_num(delta_in, nan=0.0) > args.increase_threshold_mm
    active_out = np.nan_to_num(delta_out, nan=0.0) > args.increase_threshold_mm
    duration_hours = (active_in.astype("float32") + active_out.astype("float32")) * 24.0
    # Only report a duration where the peak day itself has a valid reading
    # (matches the coverage of winter_storm_max_mm itself, which comes from
    # this same peak-day grid) -- elsewhere leave NaN (no data), not 0.
    duration_hours[np.isnan(depth_peak)] = np.nan

    transform = _snodas_transform(header_peak)
    duration_path = args.output_dir / "duration_hours.tif"
    _write_geotiff(duration_path, duration_hours, crs=ASSUMED_CRS, transform=transform, nodata=np.nan)
    n_valid = int(np.sum(~np.isnan(duration_hours)))
    print(
        f"duration_hours: shape={duration_hours.shape}, valid={n_valid}/{duration_hours.size}, "
        f"values present: {sorted(set(duration_hours[~np.isnan(duration_hours)].tolist()))[:5]}... "
        f"wrote {duration_path}"
    )

    with zipfile.ZipFile(args.prism_tmin_zip) as zf:
        tif_name = next(n for n in zf.namelist() if n.endswith(".tif") and "aux" not in n)
        with zf.open(tif_name) as fh:
            import io

            with rasterio.open(io.BytesIO(fh.read())) as src:
                tmin_c = src.read(1)
                prism_transform = src.transform
                prism_crs = src.crs
                prism_nodata = src.nodata

    tmin_f = np.where(tmin_c == prism_nodata, np.nan, tmin_c * 9.0 / 5.0 + 32.0).astype("float32")
    temp_path = args.output_dir / "air_temp_F.tif"
    _write_geotiff(temp_path, tmin_f, crs=prism_crs, transform=prism_transform, nodata=np.nan)
    n_valid_t = int(np.sum(~np.isnan(tmin_f)))
    print(
        f"air_temp_F: shape={tmin_f.shape}, valid={n_valid_t}/{tmin_f.size}, "
        f"range=[{np.nanmin(tmin_f):.1f}, {np.nanmax(tmin_f):.1f}] deg F, wrote {temp_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
