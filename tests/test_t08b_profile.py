"""Tests for the T08b (NCHRP 825 Exhibit 128) real per-link join."""

from __future__ import annotations

import pandas as pd
import pytest

from resiflow.networks.t08b_profile import compute_t08b_link_profile, derive_t08b_join_keys


def _toy_links() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "e_id": ["freeway_urban", "arterial_rural_2lane", "arterial_rural_4lane", "local"],
            "hpms_fclass": pd.array([1, 4, 4, 7], dtype="Int64"),
            "urban": [1, 0, 0, 0],
            "lanes": [4, 1, 2, 1],
        }
    )


def test_derive_t08b_join_keys():
    keys = derive_t08b_join_keys(_toy_links()).set_index("e_id")
    assert keys.loc["freeway_urban", "facility_type"] == "freeway"
    assert keys.loc["freeway_urban", "area_type"] == "Urban"
    assert keys.loc["freeway_urban", "lane_category"] == "NA"  # freeway never lane-splits

    assert keys.loc["arterial_rural_2lane", "facility_type"] == "arterial"
    assert keys.loc["arterial_rural_2lane", "area_type"] == "Rural"
    assert keys.loc["arterial_rural_2lane", "lane_category"] == "Two-lane"

    assert keys.loc["arterial_rural_4lane", "lane_category"] == "Multilane"

    assert keys.loc["local", "facility_type"] == "local_access"
    assert keys.loc["local", "area_type"] == "NA"  # local_access: single undifferentiated row
    assert keys.loc["local", "lane_category"] == "NA"


def test_compute_t08b_link_profile_matches_real_table_rows():
    profile, n_matched = compute_t08b_link_profile(_toy_links())
    assert n_matched == 4  # every toy link should find a real T08b row
    by_id = profile.set_index("e_id")
    # freeway, Urban, NA -> 60 mph, 2300 pc/h/ln (T08b's own row)
    assert by_id.loc["freeway_urban", "free_flow_speed_t08b"] == pytest.approx(60.0)
    assert by_id.loc["freeway_urban", "flow_cap_plph"] == pytest.approx(2300.0)
    # arterial, Rural, Two-lane -> 55 mph, 1600 pc/h/ln
    assert by_id.loc["arterial_rural_2lane", "flow_cap_plph"] == pytest.approx(1600.0)
    # arterial, Rural, Multilane -> 2100 pc/h/ln
    assert by_id.loc["arterial_rural_4lane", "flow_cap_plph"] == pytest.approx(2100.0)
    # local_access -> 550 pc/h/ln (UNSOURCED_DEFAULT row, still a real match)
    assert by_id.loc["local", "flow_cap_plph"] == pytest.approx(550.0)


def test_unmatched_link_gets_nan_not_invented_value():
    links = pd.DataFrame(
        {
            "e_id": ["x"],
            "hpms_fclass": pd.array([None], dtype="Int64"),  # no facility_type -> no match
            "urban": [0],
            "lanes": [2],
        }
    )
    profile, n_matched = compute_t08b_link_profile(links)
    assert n_matched == 0
    assert profile.set_index("e_id").loc["x", "flow_cap_plph"] is None or pd.isna(
        profile.set_index("e_id").loc["x", "flow_cap_plph"]
    )


def test_missing_hpms_fclass_column_raises():
    links = pd.DataFrame({"e_id": ["x"], "urban": [0], "lanes": [2]})
    with pytest.raises(KeyError, match="hpms_fclass"):
        derive_t08b_join_keys(links)


# Real T39 (Census 2010 Urban Area population) rows, confirmed via
# tests/test_census_urban_area.py and manual lookup against the live
# parameters/tables/T39_census_urban_area_population_2010.csv:
#   00199 Aberdeen--Bel Air South--Bel Air North, MD -- population 213,751
#     (> 200k "Urbanized Area" but <= NCHRP 825's own 250k small-metro cutoff)
#   00766 Akron, OH -- population 569,499 (> 250k)
_SMALL_METRO_UACE = "00199"
_LARGE_METRO_UACE = "00766"


def _toy_links_with_urban_code() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "e_id": ["small_metro_arterial", "large_metro_arterial", "small_metro_freeway"],
            "hpms_fclass": pd.array([4, 4, 1], dtype="Int64"),
            "urban": [1, 1, 1],
            "lanes": [2, 2, 4],
            "urban_code": [_SMALL_METRO_UACE, _LARGE_METRO_UACE, _SMALL_METRO_UACE],
        }
    )


def test_small_metro_adjustment_cuts_capacity_8_percent_for_arterial():
    profile, _ = compute_t08b_link_profile(_toy_links_with_urban_code())
    by_id = profile.set_index("e_id")
    # arterial, Urban, NA, real (unadjusted) row -> 35 mph, 860 pc/h/ln
    unadjusted_capacity = 860.0
    small = by_id.loc["small_metro_arterial"]
    large = by_id.loc["large_metro_arterial"]
    assert small["flow_cap_plph"] == pytest.approx(unadjusted_capacity * 0.92)
    assert large["flow_cap_plph"] == pytest.approx(unadjusted_capacity)  # >250k: untouched
    # breakpoint/slope re-derived from the adjusted capacity using T08b's
    # own documented formulas, not independently guessed.
    assert small["flow_breakpoint_plph"] == pytest.approx(0.85 * small["flow_cap_plph"])
    assert small["congestion_factor"] == pytest.approx(
        small["free_flow_speed_t08b"] / (1.15 * small["flow_cap_plph"])
    )


def test_small_metro_adjustment_does_not_touch_freeway():
    profile, _ = compute_t08b_link_profile(_toy_links_with_urban_code())
    by_id = profile.set_index("e_id")
    # freeway, Urban, NA -> 60 mph, 2300 pc/h/ln, untouched even in a small metro
    assert by_id.loc["small_metro_freeway", "flow_cap_plph"] == pytest.approx(2300.0)


def test_small_metro_adjustment_skipped_without_urban_code_column():
    # No urban_code at all on this network -- adjustment must not fabricate
    # a population it doesn't have; capacity stays at T08b's raw value.
    profile, _ = compute_t08b_link_profile(_toy_links())
    assert profile.set_index("e_id").loc["freeway_urban", "flow_cap_plph"] == pytest.approx(2300.0)
