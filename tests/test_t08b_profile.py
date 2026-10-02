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
