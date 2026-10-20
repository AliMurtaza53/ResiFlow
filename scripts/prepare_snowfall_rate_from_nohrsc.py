#!/usr/bin/env python3
"""Derive LIQUID-EQUIVALENT snowfall rate from the daily SNODAS tars on disk and compare the
resulting rate-based (SHRP2-L08 SAF/CAF) estimate, per link, against the depth-proxy
(T19-winter) estimate for the four winter-storm events.

Uses only what is already on disk (3 daily tars per event; no 6-hourly pull).

Rates computed per event (all in/hr, peak over the 2 daily windows; same windows for all):
  * snowfall_rate_swe_in_hr        PRIMARY. SNODAS 24-h snowfall accumulation (product 1025 SlL01,
                                   mm liquid equivalent). This is the classification input: the HCM /
                                   SHRP2-L08 / Hranac thresholds are liquid-equivalent.
  * snowfall_rate_depthdiff_in_hr  DIAGNOSTIC. Differenced depth (1036), clip(delta, 0). A DEPTH rate:
                                   ~8x the liquid-equivalent one; NOT valid against the thresholds.
  * snowfall_rate_swedelta_in_hr   DIAGNOSTIC. Differenced SWE snapshots (1034), clip(delta, 0). Liquid
                                   equivalent but NET of melt/sublimation (the 1025 flux is gross).

Outputs per event
  * rasters (native SNODAS grid, EPSG:4326, in/hr) under ``<raw-root>/<event dir>/snowfall_rate/``;
  * the PRIMARY (liquid-equivalent) rate raster installed as
    ``<aligned-root>/<subtype>_snowrate/event_1.tif`` -- the optional companion the winter-storm
    pipeline reads (pass --overwrite-companion to replace an existing one);
  * a per-link parquet with both estimates and their difference, and a summary CSV.
Neither estimate is chosen; they are reported side by side.

Usage::

    python scripts/prepare_snowfall_rate_from_nohrsc.py --overwrite-companion   # all four events
    python scripts/prepare_snowfall_rate_from_nohrsc.py --events uri --no-install
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from affine import Affine

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from resiflow.hazards.winter_storm_rate import (  # noqa: E402
    HCM_BINS,
    NO_SNOW_BIN,
    SNODAS_DEPTH_PREFIX,
    SNODAS_SNOWFALL_PREFIX,
    SNODAS_SWE_PREFIX,
    compare_rate_and_depth,
    hcm_snow_bin,
    header_window_hours,
    load_snodas_product,
    rate_in_hr_from_depth_grids,
    rate_in_hr_from_swe_accumulations,
    tars_chronological,
)

# event -> (hazard subtype used for the aligned-raster folder, raw directory holding the daily tars)
# NB Jonas's tars live in snodas_jan2016/, not a snodas_3day/ folder like the other three.
EVENTS = {
    "jonas": ("winter_storm", "snodas_jan2016"),
    "uri": ("winter_storm_uri", "uri_20210217/snodas_3day"),
    "elliott": ("winter_storm_elliott", "elliott_20221224/snodas_3day"),
    "snowmageddon": ("winter_storm_snowmageddon", "snowmageddon_20100206/snodas_3day"),
}
DEFAULT_LINKS = Path("C:/Users/akothaw/Desktop/data/soge_clusters/networks/faf5/faf5_road_links.gpq")
# rasters written by the earlier depth-difference-only version of this script (unit-mismatched)
_STALE_RASTERS = ("snowfall_rate_in_hr.tif", "snowfall_rate_mean_accum_in_hr.tif")


def _snodas_transform(header: dict[str, str]) -> Affine:
    return Affine(
        float(header["X-axis resolution"]), 0.0, float(header["Minimum x-axis coordinate"]),
        0.0, -float(header["Y-axis resolution"]), float(header["Maximum y-axis coordinate"]),
    )


def _write_tif(path: Path, array: np.ndarray, transform: Affine) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path, "w", driver="GTiff", height=array.shape[0], width=array.shape[1], count=1, dtype="float32",
        crs="EPSG:4326", transform=transform, nodata=np.nan, compress="deflate",
    ) as dst:
        dst.write(array.astype("float32"), 1)


def derive_event_rasters(event: str, raw_root: Path) -> dict:
    """Load the event's daily tars and compute the three rate grids + pixel-level diagnostics."""
    subtype, subdir = EVENTS[event]
    tars = tars_chronological(raw_root / subdir)
    if len(tars) < 2:
        raise SystemExit(f"{event}: need >= 2 daily SNODAS tars in {raw_root / subdir}, found {len(tars)}")

    def snapshots(prefix: str):
        grids, stamps, header = [], [], None
        for tar in tars:
            grid, header, stamp = load_snodas_product(tar, prefix)
            grids.append(grid)
            stamps.append(stamp)
        return grids, [(b - a).total_seconds() / 3600.0 for a, b in zip(stamps, stamps[1:])], header

    depth, hours, header = snapshots(SNODAS_DEPTH_PREFIX)
    depthdiff_peak, _ = rate_in_hr_from_depth_grids(depth, hours)
    swe_snap, swe_hours, _ = snapshots(SNODAS_SWE_PREFIX)
    swedelta_peak, _ = rate_in_hr_from_depth_grids(swe_snap, swe_hours)  # mm-valued snapshots: same maths

    # PRIMARY: SNODAS's own 24-h snowfall accumulation (mm liquid equivalent) for the same windows the
    # depth/SWE differences span (the tar at the END of each window).
    flux, flux_hours = [], []
    for tar in tars[1:]:
        grid, hdr, _ = load_snodas_product(tar, SNODAS_SNOWFALL_PREFIX, scale=10.0)
        flux.append(grid)
        flux_hours.append(header_window_hours(hdr))
    swe_rate = rate_in_hr_from_swe_accumulations(flux, flux_hours)

    # pixel-level cross-check on the first window: does differencing see the snowfall SNODAS says fell?
    s0 = flux[0]
    snowing = np.isfinite(s0) & (s0 >= 1.0)  # >= 1 mm liquid equivalent in the window
    d0 = np.clip(depth[1] - depth[0], 0, None)
    w0 = np.clip(swe_snap[1] - swe_snap[0], 0, None)
    both = snowing & np.isfinite(d0) & (d0 > 0)
    ratio = d0[both] / s0[both]
    pixel = {
        "pixels_snowing_per_flux": int(snowing.sum()),
        "share_snowing_but_depth_delta_zero": float(1 - both.sum() / max(snowing.sum(), 1)),
        "share_snowing_but_swe_snapshot_delta_zero": float(1 - (snowing & (w0 > 0)).sum() / max(snowing.sum(), 1)),
        "median_depth_per_swe_ratio": float(np.median(ratio)) if ratio.size else np.nan,
        "p10_depth_per_swe_ratio": float(np.percentile(ratio, 10)) if ratio.size else np.nan,
        "p90_depth_per_swe_ratio": float(np.percentile(ratio, 90)) if ratio.size else np.nan,
    }
    return {
        "subtype": subtype, "subdir": subdir, "tars": [t.name for t in tars], "hours": hours,
        "swe_rate": swe_rate, "depthdiff": depthdiff_peak, "swedelta": swedelta_peak,
        "transform": _snodas_transform(header), "pixel": pixel,
    }


def write_event_rasters(derived: dict, raw_root: Path, aligned_root: Path | None, overwrite_companion: bool) -> None:
    out_dir = raw_root / derived["subdir"].split("/")[0] / "snowfall_rate"
    for stale in _STALE_RASTERS:
        if (out_dir / stale).exists():
            (out_dir / stale).unlink()
            print(f"  removed stale depth-rate raster from the earlier version: {stale}")
    _write_tif(out_dir / "snowfall_rate_swe_in_hr.tif", derived["swe_rate"], derived["transform"])
    _write_tif(out_dir / "snowfall_rate_depthdiff_in_hr.tif", derived["depthdiff"], derived["transform"])
    _write_tif(out_dir / "snowfall_rate_swedelta_in_hr.tif", derived["swedelta"], derived["transform"])
    print(f"  wrote rasters -> {out_dir}")
    if aligned_root is not None:
        target = aligned_root / f"{derived['subtype']}_snowrate" / "event_1.tif"
        if target.exists() and not overwrite_companion:
            print(f"  companion raster exists, left untouched (use --overwrite-companion to replace): {target}")
        else:
            _write_tif(target, derived["swe_rate"], derived["transform"])
            print(f"  installed liquid-equivalent pipeline companion -> {target}")


# ------------------------------------------------------------------ per-link sampling
def link_sample_points(geometry, spacing_m: float):
    """Points every ``spacing_m`` (+ vertices) along each link, with the owning link's position."""
    import shapely

    dense = shapely.segmentize(np.asarray(geometry), spacing_m)
    coords, idx = shapely.get_coordinates(dense, return_index=True)
    return coords[:, 0], coords[:, 1], idx


def link_max_from_array(pts, n_links: int, array: np.ndarray, transform: Affine, src_crs, raster_crs) -> np.ndarray:
    """Spatial MAX over each link's sample points of a north-up raster held in memory."""
    from pyproj import Transformer

    xs, ys, idx = pts
    x, y = Transformer.from_crs(src_crs, raster_crs, always_xy=True).transform(xs, ys)
    col = np.floor((x - transform.c) / transform.a).astype(np.int64)
    row = np.floor((y - transform.f) / transform.e).astype(np.int64)
    ok = (row >= 0) & (row < array.shape[0]) & (col >= 0) & (col < array.shape[1])
    vals = np.full(len(x), np.nan)
    vals[ok] = array[row[ok], col[ok]]
    per_link = pd.Series(vals).groupby(idx).max()  # skips NaN; all-NaN link -> NaN
    return per_link.reindex(range(n_links)).to_numpy()


def build_link_table(event: str, derived: dict, links, pts, aligned_root: Path) -> pd.DataFrame:
    depth_path = aligned_root / derived["subtype"] / "event_1.tif"
    with rasterio.open(depth_path) as src:
        depth_arr, depth_tf, depth_crs = src.read(1).astype("float32"), src.transform, src.crs
    n = len(links)
    tf = derived["transform"]

    def native(arr):
        return link_max_from_array(pts, n, arr, tf, links.crs, "EPSG:4326")

    table = pd.DataFrame(
        {
            "e_id": links["e_id"].to_numpy(),
            "faf5_class": links["faf5_class"].to_numpy() if "faf5_class" in links.columns else pd.NA,
            "road_classification": links["road_classification"].to_numpy(),
            "ffs_mph": pd.to_numeric(links["Speed_Limit"], errors="coerce").fillna(55.0).to_numpy(),
            "winter_storm_max_mm": link_max_from_array(pts, n, depth_arr, depth_tf, links.crs, depth_crs),
            "snowfall_rate_swe_in_hr": native(derived["swe_rate"]),
            "snowfall_rate_depthdiff_in_hr": native(derived["depthdiff"]),
            "snowfall_rate_swedelta_in_hr": native(derived["swedelta"]),
        }
    )
    any_snow = (
        (table["winter_storm_max_mm"] > 0) | (table["snowfall_rate_swe_in_hr"] > 0)
        | (table["snowfall_rate_depthdiff_in_hr"] > 0)
    )
    table = compare_rate_and_depth(table[any_snow].reset_index(drop=True), rate_col="snowfall_rate_swe_in_hr")
    # diagnostics: what the unit-mismatched depth rate would have binned to, and whether the
    # depth rate is viable after a ~10:1 snow-to-liquid conversion
    table["hcm_bin_depthdiff_raw"] = hcm_snow_bin(table["snowfall_rate_depthdiff_in_hr"])
    table["hcm_bin_depthdiff_div10"] = hcm_snow_bin(table["snowfall_rate_depthdiff_in_hr"] / 10.0)
    table["hcm_bin_swedelta"] = hcm_snow_bin(table["snowfall_rate_swedelta_in_hr"])
    table.insert(0, "event", event)
    return table


def summarize(event: str, table: pd.DataFrame, pixel: dict) -> dict:
    s: dict = {"event": event, "links_with_any_snow": len(table)}
    d = table["winter_storm_max_mm"]
    r = table["snowfall_rate_swe_in_hr"]
    dd = table["snowfall_rate_depthdiff_in_hr"]
    snowy = d > 0
    s["links_depth_gt0"] = int(snowy.sum())
    s["links_swe_rate_gt0"] = int((r > 0).sum())
    s["links_depth_gt0_no_new_snow"] = int((snowy & (r == 0)).sum())
    s["share_depth_gt0_no_new_snow"] = float((snowy & (r == 0)).sum() / max(snowy.sum(), 1))
    for b in (NO_SNOW_BIN,) + HCM_BINS:
        s[f"bin_swe_{b}"] = int((table["hcm_snow_intensity_bin"] == b).sum())
    for b in HCM_BINS:
        s[f"bin_depthdiff_raw_{b}"] = int((table["hcm_bin_depthdiff_raw"] == b).sum())
    s["swe_rate_p50_in_hr"] = float(r[r > 0].median())
    s["swe_rate_p99_in_hr"] = float(r[r > 0].quantile(0.99))
    s["swe_rate_max_in_hr"] = float(r.max())
    # ---- T19 depth proxy vs the rate-based SAF/CAF (links with depth > 0)
    t = table[snowy]
    s["t19_ratio_median"] = float(t["depth_speed_ratio_t19"].median())
    s["t19_closed_share"] = float((t["depth_speed_ratio_t19"] == 0).mean())
    s["saf_mean"] = float(t["rate_speed_factor"].mean())
    s["saf_min"] = float(t["rate_speed_factor"].min())
    s["caf_mean"] = float(t["rate_cap_factor"].mean())
    s["rate_ffs_extrapolated_share"] = float(t["rate_ffs_extrapolated"].mean())
    s["mean_diff_t19_minus_saf"] = float(t["speed_ratio_diff_t19_minus_saf"].mean())
    s["median_diff_t19_minus_saf"] = float(t["speed_ratio_diff_t19_minus_saf"].median())
    for tag, sub in (("all", t), ("new_snow", t[t["snowfall_rate_swe_in_hr"] > 0]), ("no_new_snow", t[t["snowfall_rate_swe_in_hr"] == 0])):
        n = max(len(sub), 1)
        s[f"n_{tag}"] = len(sub)
        for v in ("within", "t19_lower", "t19_higher", "n/a"):
            s[f"t19_vs_saf_{tag}_{v}"] = int((sub["t19_vs_saf"] == v).sum())
        s[f"t19_vs_saf_{tag}_lower_share"] = float((sub["t19_vs_saf"] == "t19_lower").sum() / n)
    both = snowy & (r > 0)
    s["spearman_depth_vs_swe_rate"] = float(d[both].corr(r[both], method="spearman")) if both.sum() > 2 else np.nan
    closed = t[t["depth_speed_ratio_t19"] == 0]
    s["t19_closed_links"] = len(closed)
    s["t19_closed_no_new_snow_share"] = float((closed["snowfall_rate_swe_in_hr"] == 0).mean())
    s["t19_closed_light_or_none_share"] = float(closed["hcm_snow_intensity_bin"].isin(["none", "light"]).mean())
    # ---- is depth differencing viable once units are handled (depth rate / 10)?
    both_dd = (r > 0) & (dd > 0)
    s["spearman_depthdiff_vs_swe_rate"] = float(dd[both_dd].corr(r[both_dd], method="spearman")) if both_dd.sum() > 2 else np.nan
    pos = r > 0
    s["swe_pos_but_depthdiff_zero_share"] = float((pos & (dd == 0)).sum() / max(pos.sum(), 1))
    scope = pos | (dd > 0)
    s["bin_agree_depthdiff_div10_vs_swe"] = float((table.loc[scope, "hcm_bin_depthdiff_div10"] == table.loc[scope, "hcm_snow_intensity_bin"]).mean())
    s["bin_agree_depthdiff_raw_vs_swe"] = float((table.loc[scope, "hcm_bin_depthdiff_raw"] == table.loc[scope, "hcm_snow_intensity_bin"]).mean())
    s["bin_agree_swedelta_vs_swe"] = float((table.loc[scope, "hcm_bin_swedelta"] == table.loc[scope, "hcm_snow_intensity_bin"]).mean())
    s.update({f"pixel_{k}": v for k, v in pixel.items()})
    return s


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--events", nargs="+", choices=sorted(EVENTS), default=sorted(EVENTS))
    p.add_argument("--raw-root", type=Path, default=REPO_ROOT / "inputs" / "multihazard_raw" / "winter_storm")
    p.add_argument("--aligned-root", type=Path, default=REPO_ROOT / "inputs" / "multihazard_aligned")
    p.add_argument("--links", type=Path, default=DEFAULT_LINKS)
    p.add_argument("--out-dir", type=Path, default=REPO_ROOT / "results" / "winter_rate_comparison")
    p.add_argument("--no-install", action="store_true", help="do not drop the companion raster into --aligned-root")
    p.add_argument("--overwrite-companion", action="store_true", help="replace an existing companion raster")
    p.add_argument("--no-compare", action="store_true", help="rasters only; skip the per-link comparison")
    p.add_argument("--sample-spacing-m", type=float, default=500.0)
    args = p.parse_args()

    links = pts = None
    summaries = []
    for event in args.events:
        print(f"\n== {event} ==")
        derived = derive_event_rasters(event, args.raw_root)
        print(f"  tars: {derived['tars']}  interval hours: {derived['hours']}")
        write_event_rasters(derived, args.raw_root, None if args.no_install else args.aligned_root, args.overwrite_companion)
        if args.no_compare:
            continue
        if links is None:
            import geopandas as gpd

            links = gpd.read_parquet(args.links, columns=["e_id", "faf5_class", "road_classification", "Speed_Limit", "geometry"])
            pts = link_sample_points(links.geometry.values, args.sample_spacing_m)
            print(f"  sampling {len(links)} links at {len(pts[0])} points (<= {args.sample_spacing_m:.0f} m apart)")
        table = build_link_table(event, derived, links, pts, args.aligned_root)
        args.out_dir.mkdir(parents=True, exist_ok=True)
        table.to_parquet(args.out_dir / f"{event}_link_comparison.parquet", index=False)
        summaries.append(summarize(event, table, derived["pixel"]))
        print(f"  wrote {len(table)} link rows -> {args.out_dir / (event + '_link_comparison.parquet')}")
    if summaries:
        pd.DataFrame(summaries).set_index("event").T.to_csv(args.out_dir / "summary.csv")
        print(f"\nSummary -> {args.out_dir / 'summary.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
