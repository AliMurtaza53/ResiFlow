"""Rate-based winter estimate (T19-ALT v2): liquid-equivalent snowfall rate -> SHRP2-L08 bin -> SAF/CAF.

A SECOND, PARALLEL estimate that runs alongside the depth-proxy crosswalk
(``fragility/winter_storm_speed.py``, T19-winter). It never drives ``max_speed``;
it only adds columns so the two can be compared before either is chosen.

UNITS (settled): the HCM / SHRP2-L08 (Exhibit 36-25) / Hranac intensity thresholds
are LIQUID-EQUIVALENT precipitation rates (ASOS/AWOS gauges measure liquid
equivalent only). The classification input is therefore
``snowfall_rate_swe_in_hr`` -- SNODAS's own 24-h snowfall accumulation (product
1025, SlL01; raw int / 10 = mm liquid equivalent) over the same 24-h windows the
depth differences span. A depth-DIFFERENCED rate (product 1036) is a different
quantity (snow depth runs ~8-12x liquid equivalent; measured here at 7.5-8.4x)
and must not be binned against these thresholds; it is kept only as a diagnostic
(``snowfall_rate_depthdiff_in_hr``), as is the SWE-snapshot-differenced rate
(product 1034, ``snowfall_rate_swedelta_in_hr``: NET of melt/sublimation, where
the 1025 flux is gross snowfall).

Other things a reader must know:

* Daily data gives a 24-h MEAN rate; the tables were calibrated on hourly gauge
  rates, so 24-h means sit systematically lower in the bin ladder.
* SNODAS product codes: 1036 = snow layer thickness (depth), 1034 = snow water
  equivalent, 1025 SlL01 = snowfall accumulation, 1025 SlL00 = non-snow (rain).
* SAF/CAF come from SHRP2-L08 Exhibit 36-25 (freeways only; 55-75 mph free-flow
  speed). Arterials/ramps (free-flow outside 55-75 mph) take the nearest tabulated
  column and are flagged ``rate_ffs_extrapolated``. The "severe cold" (<-4 F) row is a
  temperature-only category and is NOT applied here.
* Hranac city ranges (valid to ~0.12 in/hr) are kept as a regional cross-check.
"""

from __future__ import annotations

import csv
import gzip
import re
import tarfile
import warnings
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from resiflow.tables import tables_root

MM_PER_IN = 25.4
HCM_BIN_EDGES_IN_HR = (0.05, 0.10, 0.50)  # (0,0.05] light, (0.05,0.10] light-medium, (0.10,0.50] medium-heavy, >0.50 heavy
HCM_BINS = ("light", "light-medium", "medium-heavy", "heavy")
NO_SNOW_BIN = "none"
HRANAC_VALID_MAX_IN_HR = 0.12  # Hranac: "snow 0 to ~0.3 cm/hr (~0.12 in/hr); limited data above"
HRANAC_LIGHT_MAX_IN_HR = 0.004  # "<0.01 cm/hr (<0.004 in/hr)" row
AGREEMENT_TOL = 0.10  # |T19 speed ratio - SAF| within this counts as "within" (a reporting choice, not sourced)

SNODAS_DEPTH_PREFIX = "us_ssmv11036"  # snow layer thickness, raw int = mm
SNODAS_SWE_PREFIX = "us_ssmv11034"  # snow water equivalent snapshot, raw int = mm
SNODAS_SNOWFALL_PREFIX = "us_ssmv01025SlL01"  # 24-h snowfall accumulation, raw int / 10 = mm liquid equivalent
_NODATA = -9999.0
_ARTIFACT_SENTINEL = 32767.0  # fixed-location model artifact, see scripts/prepare_snodas_depth.py

T19_ALT_TABLE = "T19_alt_snowfall_rate_speed_capacity.csv"


# ---------------------------------------------------------------- SNODAS reading
def _parse_header(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            out[key.strip()] = value.strip()
    return out


def load_snodas_product(tar_path: Path, prefix: str, *, scale: float = 1.0) -> tuple[np.ndarray, dict[str, str], datetime]:
    """One SNODAS product from a daily tar: (float32 grid with NaN nodata, header, stop timestamp UTC)."""
    with tarfile.open(tar_path) as tf:
        members = {m.name: m for m in tf.getmembers()}
        txt = next((n for n in members if n.startswith(prefix) and n.endswith(".txt.gz")), None)
        dat = next((n for n in members if n.startswith(prefix) and n.endswith(".dat.gz")), None)
        if txt is None or dat is None:
            raise FileNotFoundError(f"No {prefix}* product in {tar_path}")
        header = _parse_header(gzip.decompress(tf.extractfile(txt).read()).decode())
        raw = gzip.decompress(tf.extractfile(dat).read())
    ncols, nrows = int(header["Number of columns"]), int(header["Number of rows"])
    arr = np.frombuffer(raw, dtype=">i2").reshape(nrows, ncols).astype("float64")
    valid = (arr != float(header.get("No data value", _NODATA))) & (arr != _ARTIFACT_SENTINEL)
    grid = np.full(arr.shape, np.nan, dtype="float32")
    grid[valid] = (arr[valid] / scale).astype("float32")
    stamp = datetime(
        int(header["Stop year"]), int(header["Stop month"]), int(header["Stop day"]), int(header["Stop hour"])
    )
    return grid, header, stamp


def header_window_hours(header: dict[str, str]) -> float:
    """Hours covered by an accumulation product (Stop - Start timestamps in its header)."""
    def stamp(prefix: str) -> datetime:
        return datetime(*(int(header[f"{prefix} {u}"]) for u in ("year", "month", "day", "hour")))

    return (stamp("Stop") - stamp("Start")).total_seconds() / 3600.0


def tars_chronological(directory: Path) -> list[Path]:
    """SNODAS_YYYYMMDD.tar files in a directory, oldest first."""
    found = sorted(directory.glob("SNODAS_*.tar"), key=lambda p: re.search(r"(\d{8})", p.name).group(1))
    return [p for p in found if re.fullmatch(r"SNODAS_\d{8}\.tar", p.name)]


# -------------------------------------------------------------------- rate maths
def rate_in_hr_from_depth_grids(
    depth_mm_grids: list[np.ndarray], hours_between: list[float]
) -> tuple[np.ndarray, np.ndarray]:
    """Spec pseudocode: per interval delta = clip(g[i]-g[i-1], 0), rate = delta/hours/25.4.

    Works on any mm-valued snapshot grids (depth 1036 or SWE 1034). Returns (peak_rate,
    mean_accum_rate) in in/hr -- the max over intervals, and the mean over intervals that
    accumulated. NaN where every interval is NaN. NOTE: for DEPTH grids this is a depth rate,
    not a liquid-equivalent one (see module docstring).
    """
    if len(depth_mm_grids) < 2 or len(hours_between) != len(depth_mm_grids) - 1:
        raise ValueError("need >= 2 grids and len(hours_between) == len(grids) - 1")
    rates = []
    for i in range(1, len(depth_mm_grids)):
        delta = np.clip(depth_mm_grids[i] - depth_mm_grids[i - 1], 0, None)  # NaN stays NaN
        rates.append(delta / hours_between[i - 1] / MM_PER_IN)
    stack = np.stack(rates)
    with np.errstate(all="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN slices (nodata pixels) are expected
        peak = np.nanmax(stack, axis=0)
        accumulating = np.where(stack > 0, stack, np.nan)
        mean_accum = np.nan_to_num(np.nanmean(accumulating, axis=0), nan=0.0)
    all_nan = np.isnan(stack).all(axis=0)
    mean_accum[all_nan] = np.nan
    return peak.astype("float32"), mean_accum.astype("float32")


def rate_in_hr_from_swe_accumulations(swe_mm_grids: list[np.ndarray], hours: list[float]) -> np.ndarray:
    """Peak liquid-equivalent rate in in/hr from 24-h SNODAS snowfall accumulations (mm LWE)."""
    stack = np.stack([np.clip(g, 0, None) / h / MM_PER_IN for g, h in zip(swe_mm_grids, hours)])
    with np.errstate(all="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        peak = np.nanmax(stack, axis=0)
    return peak.astype("float32")


def hcm_snow_bin(rate_in_hr) -> np.ndarray:
    """HCM snow-intensity bin per value: none | light | light-medium | medium-heavy | heavy (NaN -> NaN)."""
    rate = np.asarray(pd.to_numeric(pd.Series(rate_in_hr), errors="coerce"), dtype=float)
    idx = np.searchsorted(np.asarray(HCM_BIN_EDGES_IN_HR), rate, side="left")  # (edge_{k-1}, edge_k]
    labels = np.array(HCM_BINS, dtype=object)[np.clip(idx, 0, 3)]
    labels = np.where(rate > 0, labels, NO_SNOW_BIN).astype(object)
    labels[np.isnan(rate)] = np.nan
    return labels


# ---------------------------------------------------------------- T19-ALT tables
@lru_cache(maxsize=1)
def load_t19_alt(params_root: str | None = None) -> dict:
    """SHRP2-L08 CAF and SAF by (bin, free-flow speed), plus Hranac free-flow-speed reduction ranges."""
    path = Path(tables_root(params_root)) / T19_ALT_TABLE
    ffs_cols: list[float] = []
    factors: dict[str, dict[str, np.ndarray]] = {"CAF": {}, "SAF": {}}
    hranac: dict[str, tuple[float, float]] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if not row or row[0].startswith("#"):
                continue
            if row[0] == "weather_type" and "metric" in row:
                ffs_cols = [float(re.search(r"(\d+)", c).group(1)) for c in row if c.startswith("ffs_")]
                continue
            if len(row) >= 8 and row[2] in factors:  # snow rows only; cold/nonsevere rows are not bins
                bin_name = row[0].replace(" snow", "").strip().lower()
                if bin_name in HCM_BINS:
                    factors[row[2]][bin_name] = np.array([float(v) for v in row[3:8]])
            elif len(row) >= 4 and row[2] == "Free-flow speed" and row[0] in ("Light snow", "Snow"):
                lo, hi = (float(v) / 100.0 for v in re.findall(r"-?\d+", row[3].replace("%", "")))
                hranac["light" if "<0.01" in row[1] else "snow_0.3cm"] = (abs(lo), abs(hi))  # (min, max) reduction, +fractions
    missing = [f"{m}:{b}" for m in factors for b in HCM_BINS if b not in factors[m]]
    if missing or not ffs_cols or len(hranac) != 2:
        raise ValueError(f"{T19_ALT_TABLE}: could not parse (missing {missing}, hranac {list(hranac)})")
    return {"ffs": np.array(ffs_cols), "caf": factors["CAF"], "saf": factors["SAF"], "hranac_reduction": hranac}


def _interp_factor(table: str, bins: np.ndarray, ffs_mph) -> tuple[np.ndarray, np.ndarray]:
    t = load_t19_alt()
    ffs = np.asarray(pd.to_numeric(pd.Series(ffs_mph), errors="coerce"), dtype=float)
    out = np.full(len(bins), np.nan)
    for name, values in t[table].items():
        mask = np.asarray(bins == name)
        out[mask] = np.interp(ffs[mask], t["ffs"], values)  # clamps at the ends; NaN ffs -> NaN
    out[np.asarray(bins == NO_SNOW_BIN)] = 1.0  # SHRP2 "nonsevere weather" baseline
    extrapolated = ~((ffs >= t["ffs"].min()) & (ffs <= t["ffs"].max()))
    return out, extrapolated


def capacity_factor(bins: np.ndarray, ffs_mph) -> tuple[np.ndarray, np.ndarray]:
    """SHRP2-L08 CAF for (bin, free-flow speed): linear across 55-75 mph, clamped outside.

    Returns (caf, ffs_extrapolated); ``ffs_extrapolated`` marks free-flow speeds outside the
    55-75 mph calibration (or unknown), where the value is the nearest tabulated column.
    """
    return _interp_factor("caf", bins, ffs_mph)


def speed_adjustment_factor(bins: np.ndarray, ffs_mph) -> tuple[np.ndarray, np.ndarray]:
    """SHRP2-L08 SAF for (bin, free-flow speed); same interpolation/flagging as ``capacity_factor``."""
    return _interp_factor("saf", bins, ffs_mph)


def hranac_speed_ratio_range(rate_in_hr) -> tuple[np.ndarray, np.ndarray]:
    """(lo, hi) speed ratio (1 - reduction) from Hranac Table ES.2 free-flow-speed ranges (cross-check).

    <=0.004 in/hr uses the "<0.01 cm/hr" row, up to 0.12 in/hr the "~0.3 cm/hr" row; NaN above
    0.12 in/hr (outside the study's validity range); (1, 1) where there is no snow.
    """
    t = load_t19_alt()["hranac_reduction"]
    rate = np.asarray(pd.to_numeric(pd.Series(rate_in_hr), errors="coerce"), dtype=float)
    lo = np.full(len(rate), np.nan)
    hi = np.full(len(rate), np.nan)
    light = (rate > 0) & (rate <= HRANAC_LIGHT_MAX_IN_HR)
    snow = (rate > HRANAC_LIGHT_MAX_IN_HR) & (rate <= HRANAC_VALID_MAX_IN_HR)
    for mask, key in ((light, "light"), (snow, "snow_0.3cm")):
        rmin, rmax = t[key]
        lo[mask], hi[mask] = 1.0 - rmax, 1.0 - rmin
    none = rate == 0
    lo[none] = hi[none] = 1.0
    return lo, hi


# ------------------------------------------------------------------- comparison
def _verdict(t19: pd.Series, ref: pd.Series, tol: float) -> np.ndarray:
    return np.select(
        [t19.isna() | ref.isna(), t19 < ref - tol - 1e-9, t19 > ref + tol + 1e-9],
        ["n/a", "t19_lower", "t19_higher"],
        default="within",
    )


def compare_rate_and_depth(
    links: pd.DataFrame,
    *,
    depth_col: str = "winter_storm_max_mm",
    rate_col: str = "snowfall_rate_swe_in_hr",
    ffs_col: str = "ffs_mph",
) -> pd.DataFrame:
    """Add the rate-based estimate and its difference from the T19 depth-proxy estimate.

    ``rate_col`` must be a LIQUID-EQUIVALENT rate (in/hr). Adds: hcm_snow_intensity_bin,
    rate_cap_factor (CAF), rate_speed_factor (SAF), rate_ffs_extrapolated, depth_speed_ratio_t19
    (car), speed_ratio_diff_t19_minus_saf, t19_vs_saf (within +/-AGREEMENT_TOL | t19_lower |
    t19_higher | n/a), and the Hranac cross-check (hranac_speed_ratio_lo/hi, t19_vs_hranac).
    Neither estimate is modified or preferred.
    """
    from resiflow.fragility.winter_storm_speed import speed_ratio

    out = links.copy()
    rate = pd.to_numeric(out[rate_col], errors="coerce")
    bins = hcm_snow_bin(rate)
    out["hcm_snow_intensity_bin"] = bins
    ffs = out[ffs_col].to_numpy(dtype=float)
    out["rate_cap_factor"], out["rate_ffs_extrapolated"] = capacity_factor(bins, ffs)
    out["rate_speed_factor"], _ = speed_adjustment_factor(bins, ffs)
    depth = pd.to_numeric(out[depth_col], errors="coerce")
    t19 = pd.Series(np.where(depth.notna(), speed_ratio(depth.fillna(0.0)), np.nan), index=out.index)
    out["depth_speed_ratio_t19"] = t19
    out["speed_ratio_diff_t19_minus_saf"] = t19 - out["rate_speed_factor"]
    out["t19_vs_saf"] = _verdict(t19, out["rate_speed_factor"], AGREEMENT_TOL)
    lo, hi = hranac_speed_ratio_range(rate)
    out["hranac_speed_ratio_lo"], out["hranac_speed_ratio_hi"] = lo, hi
    out["t19_vs_hranac"] = np.select(
        [np.isnan(lo) | t19.isna(), t19 < lo - 1e-9, t19 > hi + 1e-9],
        ["n/a", "t19_lower", "t19_higher"],
        default="within",
    )
    return out
