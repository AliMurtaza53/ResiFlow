"""Rate-based (T19-ALT) winter estimate: SNODAS differencing, HCM bins, CAF/Hranac, parallel columns."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from affine import Affine

from resiflow.hazards.winter_storm_rate import (
    capacity_factor,
    compare_rate_and_depth,
    hcm_snow_bin,
    header_window_hours,
    hranac_speed_ratio_range,
    load_snodas_product,
    load_t19_alt,
    rate_in_hr_from_depth_grids,
    rate_in_hr_from_swe_accumulations,
    speed_adjustment_factor,
    tars_chronological,
    SNODAS_DEPTH_PREFIX,
    SNODAS_SNOWFALL_PREFIX,
    SNODAS_SWE_PREFIX,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
RAW = REPO_ROOT / "inputs" / "multihazard_raw" / "winter_storm"


def _script():
    spec = importlib.util.spec_from_file_location("prep_rate", REPO_ROOT / "scripts" / "prepare_snowfall_rate_from_nohrsc.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------------------------- differencing
def test_rate_differencing_clips_negatives_uses_hours_and_converts_units() -> None:
    d0 = np.array([[0.0, 100.0, 10.0, np.nan]], dtype="float32")
    d1 = np.array([[25.4, 50.0, 10.0, 5.0]], dtype="float32")  # +25.4 mm | melt/settle | flat | nodata-before
    d2 = np.array([[25.4, 50.0, 71.0, 9.0]], dtype="float32")  # flat | flat | +61 mm | ...
    peak, mean_accum = rate_in_hr_from_depth_grids([d0, d1, d2], [24.0, 24.0])
    # pixel 0: only interval 1 accumulated: 25.4 mm / 24 h / 25.4 = 1/24 in/hr
    assert peak[0, 0] == pytest.approx(1 / 24, rel=1e-5) and mean_accum[0, 0] == pytest.approx(1 / 24, rel=1e-5)
    assert peak[0, 1] == 0.0 and mean_accum[0, 1] == 0.0  # negative delta ignored, not a negative rate
    assert peak[0, 2] == pytest.approx(61.0 / 24 / 25.4, rel=1e-5)
    assert peak[0, 3] == pytest.approx(4.0 / 24 / 25.4, rel=1e-5)  # NaN interval skipped; the valid one still counts
    peak6, _ = rate_in_hr_from_depth_grids([d0, d1], [6.0])  # hours matter: 6-h window -> 4x the 24-h rate
    assert peak6[0, 0] == pytest.approx(4 / 24, rel=1e-5)


def test_rate_differencing_rejects_bad_input() -> None:
    with pytest.raises(ValueError):
        rate_in_hr_from_depth_grids([np.zeros((1, 1))], [])
    with pytest.raises(ValueError):
        rate_in_hr_from_depth_grids([np.zeros((1, 1))] * 3, [24.0])


def test_swe_rate_is_liquid_equivalent_in_per_hr() -> None:
    peak = rate_in_hr_from_swe_accumulations([np.array([[25.4, 0.0]]), np.array([[0.0, 50.8]])], [24.0, 24.0])
    assert peak[0, 0] == pytest.approx(1 / 24, rel=1e-5) and peak[0, 1] == pytest.approx(2 / 24, rel=1e-5)


# ------------------------------------------------------------------------ HCM bins
def test_hcm_bin_edges_are_upper_inclusive() -> None:
    r = [0.0, 1e-6, 0.05, 0.0500001, 0.10, 0.1000001, 0.50, 0.5000001, np.nan]
    assert list(hcm_snow_bin(r)[:-1]) == [
        "none", "light", "light", "light-medium", "light-medium", "medium-heavy", "medium-heavy", "heavy",
    ]
    assert pd.isna(hcm_snow_bin(r)[-1])


# --------------------------------------------------------------- T19-ALT tables
def test_t19_alt_tables_parse() -> None:
    t = load_t19_alt()
    assert list(t["ffs"]) == [55, 60, 65, 70, 75]
    assert t["caf"]["light"][0] == 0.97 and t["caf"]["heavy"][-1] == 0.72
    assert set(t["caf"]) == {"light", "light-medium", "medium-heavy", "heavy"}  # cold/visibility rows are not snow bins
    lo, hi = t["hranac_reduction"]["light"]
    assert (lo, hi) == (0.05, 0.16) and t["hranac_reduction"]["snow_0.3cm"] == (0.05, 0.19)
    # v2: SHRP2-L08 Exhibit 36-25 speed factors are present for every snow bin, and worsen with intensity
    assert set(t["saf"]) == {"light", "light-medium", "medium-heavy", "heavy"}
    assert list(t["saf"]["light"]) == [0.94, 0.92, 0.89, 0.87, 0.84] and t["saf"]["heavy"][-1] == 0.81
    assert [t["saf"][b][0] for b in ("light", "light-medium", "medium-heavy", "heavy")] == [0.94, 0.92, 0.90, 0.88]


def test_speed_adjustment_factor_interpolates_and_flags() -> None:
    bins = np.array(["light", "heavy", "none", "medium-heavy"], dtype=object)
    saf, extrapolated = speed_adjustment_factor(bins, np.array([57.5, 75.0, 30.0, 45.0]))
    assert saf[0] == pytest.approx(0.93)  # midway between 0.94 (55) and 0.92 (60)
    assert saf[1] == 0.81 and saf[2] == 1.0
    assert saf[3] == 0.90  # 45 mph clamps to the 55-mph column
    assert list(extrapolated) == [False, False, True, True]


def test_capacity_factor_interpolates_and_flags_out_of_calibration_speeds() -> None:
    bins = np.array(["light", "light", "light", "heavy", "none"], dtype=object)
    caf, extrapolated = capacity_factor(bins, np.array([57.5, 45.0, 80.0, 75.0, 30.0]))
    assert caf[0] == pytest.approx(0.965)  # midway between 0.97 (55) and 0.96 (60)
    assert caf[1] == 0.97 and caf[2] == 0.95  # clamped to the nearest tabulated column
    assert caf[3] == 0.72 and caf[4] == 1.0
    assert list(extrapolated) == [False, True, True, False, True]


def test_hranac_range_is_ordered_and_only_valid_up_to_0p12_in_hr() -> None:
    lo, hi = hranac_speed_ratio_range(np.array([0.0, 0.003, 0.05, 0.12, 0.13, np.nan]))
    assert lo[0] == hi[0] == 1.0
    assert (lo[1], hi[1]) == (pytest.approx(0.84), pytest.approx(0.95))
    assert (lo[2], hi[2]) == (pytest.approx(0.81), pytest.approx(0.95))
    assert lo[3] == pytest.approx(0.81)
    assert np.isnan(lo[4]) and np.isnan(hi[4]) and np.isnan(lo[5])  # outside validity: no speed estimate
    assert (lo[:4] <= hi[:4]).all()


# --------------------------------------------------------------- the comparison
def test_compare_reports_both_estimates_and_their_difference_without_choosing() -> None:
    links = pd.DataFrame(
        {
            "winter_storm_max_mm": [0.0, 13.0, 102.0, 300.0, 40.0],
            "snowfall_rate_swe_in_hr": [0.001, 0.05, 0.05, 0.30, 0.0],
            "ffs_mph": [65.0, 65.0, 45.0, 70.0, 60.0],
        }
    )
    out = compare_rate_and_depth(links)
    assert list(out["hcm_snow_intensity_bin"]) == ["light", "light", "light", "medium-heavy", "none"]
    assert list(out["depth_speed_ratio_t19"][:4]) == [1.0, pytest.approx(0.9), pytest.approx(0.65), 0.0]
    # SHRP2-L08: light@65 SAF 0.89; light@45 clamps to 55-mph 0.94; medium-heavy@70 SAF 0.84, CAF 0.88; none = 1.0
    assert list(out["rate_speed_factor"]) == [pytest.approx(0.89), pytest.approx(0.89), pytest.approx(0.94), pytest.approx(0.84), 1.0]
    assert out["rate_cap_factor"].iloc[3] == pytest.approx(0.88)
    assert list(out["rate_ffs_extrapolated"]) == [False, False, True, False, False]
    # T19 - SAF with a +/-0.10 tolerance: 1.00-0.89=+0.11 (higher) | +0.01 (within) | -0.29 | closed vs 0.84 | ~0.835-1.0
    assert list(out["t19_vs_saf"]) == ["t19_higher", "within", "t19_lower", "t19_lower", "t19_lower"]
    assert out["speed_ratio_diff_t19_minus_saf"].iloc[2] == pytest.approx(0.65 - 0.94)
    # Hranac cross-check retained (valid only up to 0.12 in/hr): row 3 (0.30 in/hr) is outside it
    assert list(out["t19_vs_hranac"]) == ["t19_higher", "within", "t19_lower", "n/a", "t19_lower"]
    assert list(links.columns) == ["winter_storm_max_mm", "snowfall_rate_swe_in_hr", "ffs_mph"]  # input untouched


def test_builder_adds_rate_columns_without_changing_max_speed() -> None:
    from resiflow.disruption.build import build_winter_storm_link_disruption
    from resiflow.disruption.winter_storm import classify_merged_intersections

    road_links = pd.DataFrame(
        {
            "e_id": ["A", "B"],
            "faf5_class": [11, 14],
            "from_id": [1, 3],
            "to_id": [2, 4],
            "road_classification": ["motorway", "primary"],
        }
    )

    def run(with_rate: bool) -> pd.DataFrame:
        inter = pd.DataFrame(
            {
                "e_id": ["A", "B"], "length": 1.0, "index_i": 0, "index_j": 0,
                "road_classification": ["motorway", "primary"],
                "winter_storm_mm": [150.0, 40.0], "duration_hours": [24.0, 0.0], "air_temp_F": [20.0, 30.0],
            }
        )
        if with_rate:
            inter["snowfall_rate_swe_in_hr"] = [0.08, np.nan]
        inter = classify_merged_intersections(inter, road_links)
        return build_winter_storm_link_disruption(
            road_links, inter, pd.DataFrame({"e_id": ["A", "B"], "free_flow_speeds": [65.0, 65.0]}),
            hazard_event=SimpleNamespace(event_id="1"), scenario_param=601,
        ).set_index("e_id")

    base, both = run(False), run(True)
    assert "hcm_snow_intensity_bin" not in base.columns  # optional: absent raster -> nothing added
    assert list(both["max_speed"]) == list(base["max_speed"])  # T19 still drives speed
    assert list(both["damage_level_max"]) == list(base["damage_level_max"])
    assert both.loc["A", "hcm_snow_intensity_bin"] == "light-medium" and pd.isna(both.loc["B", "hcm_snow_intensity_bin"])
    assert both.loc["A", "rate_cap_factor"] == pytest.approx(0.92)  # light-medium @ 65 mph
    assert both.loc["A", "rate_speed_factor"] == pytest.approx(0.88)
    assert both.loc["A", "depth_speed_ratio_t19"] == pytest.approx(both.loc["A", "max_speed"] / 65.0)


# ------------------------------------------------------- script helpers + real tars
def test_link_max_takes_the_max_over_sample_points_along_the_link() -> None:
    import shapely

    mod = _script()
    grid = np.array([[1.0, 5.0, 2.0], [0.0, 0.0, 0.0]], dtype="float32")
    tf = Affine(1.0, 0.0, 0.0, 0.0, -1.0, 2.0)  # x 0..3, y 0..2, north-up
    lines = np.array([shapely.linestrings([[0.1, 1.5], [2.9, 1.5]]), shapely.linestrings([[0.1, 0.5], [2.9, 0.5]])])
    pts = mod.link_sample_points(lines, spacing_m=0.5)
    out = mod.link_max_from_array(pts, 2, grid, tf, "EPSG:4326", "EPSG:4326")
    assert list(out) == [5.0, 0.0]
    off = mod.link_max_from_array(mod.link_sample_points(np.array([shapely.linestrings([[10, 10], [11, 10]])]), 0.5), 1, grid, tf, "EPSG:4326", "EPSG:4326")
    assert np.isnan(off[0])  # outside the raster -> NaN, not 0


@pytest.mark.skipif(not RAW.exists(), reason="raw SNODAS tars not on disk")
def test_event_tars_are_chronological_daily_and_products_are_the_documented_ones() -> None:
    mod = _script()
    for event, (_subtype, subdir) in mod.EVENTS.items():
        tars = tars_chronological(RAW / subdir)
        assert len(tars) == 3, (event, tars)
        assert [t.name for t in tars] == sorted(t.name for t in tars)
    tar = tars_chronological(RAW / mod.EVENTS["uri"][1])[1]  # peak day 2021-02-17
    depth, _hdr, stamp = load_snodas_product(tar, SNODAS_DEPTH_PREFIX)
    assert (stamp.year, stamp.month, stamp.day, stamp.hour) == (2021, 2, 17, 6)
    assert np.nanmax(depth) < 32000 and np.nanmin(depth) >= 0  # mm; 32767 artifact masked
    swe, hdr, _ = load_snodas_product(tar, SNODAS_SNOWFALL_PREFIX, scale=10.0)
    assert header_window_hours(hdr) == 24.0
    assert np.nanmax(swe) < 1000  # mm liquid equivalent per day (scale 10 applied)
    snap, _, _ = load_snodas_product(tar, SNODAS_SWE_PREFIX)  # product 1034: SWE snapshot, mm
    assert np.nanmin(snap) >= 0 and np.nanmax(snap) < 32000
