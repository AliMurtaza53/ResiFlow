"""Tests for T24 CP25 per-link road reconstruction cost."""

from __future__ import annotations

import pandas as pd
import pytest

from resiflow.networks.cp25_road_cost import cp25_road_cost_usd_per_lane_mile


def test_rural_interstate_default_terrain_matches_real_table_row():
    # T24 CP25: Rural, Interstate, Rolling, Total Reconstruct Existing Lane
    # = 2041 ($K/lane-mi 2018) -- TERRAIN_DEFAULT is "Rolling".
    cost = cp25_road_cost_usd_per_lane_mile(
        hpms_fclass=pd.Series([1]),
        urban=pd.Series([0]),
        urban_size_tier=pd.Series([pd.NA]),
    )
    assert cost.iloc[0] == pytest.approx(2041 * 1000.0)


def test_real_terrain_overrides_default_when_known():
    cost = cp25_road_cost_usd_per_lane_mile(
        hpms_fclass=pd.Series([1, 1, 1]),
        urban=pd.Series([0, 0, 0]),
        urban_size_tier=pd.Series([pd.NA, pd.NA, pd.NA]),
        terrain_type=pd.Series(["Flat", "Mountainous", None]),
    )
    assert cost.iloc[0] == pytest.approx(1732 * 1000.0)  # Rural Interstate Flat
    assert cost.iloc[1] == pytest.approx(2583 * 1000.0)  # Rural Interstate Mountainous
    assert cost.iloc[2] == pytest.approx(2041 * 1000.0)  # missing -> default Rolling


def test_urban_small_urbanized_matches_real_table_row():
    # T24 CP25: Urban, Minor Arterial, Small Urbanized, Total Reconstruct
    # Existing Lane.
    cost = cp25_road_cost_usd_per_lane_mile(
        hpms_fclass=pd.Series([4]),
        urban=pd.Series([1]),
        urban_size_tier=pd.Series(["small_urbanized"]),
    )
    from resiflow.networks.cp25_road_cost import load_t24_cp25

    t24 = load_t24_cp25()
    expected_row = t24[
        (t24["region"] == "Urban")
        & (t24["functional_class"] == "Minor Arterial")
        & (t24["subcategory_or_terrain"] == "Small Urbanized")
        & (t24["improvement_type"] == "Total Reconstruct Existing Lane")
    ]
    assert len(expected_row) == 1
    assert cost.iloc[0] == pytest.approx(
        expected_row.iloc[0]["cost_thousand_2018usd_per_lane_mile"] * 1000.0
    )


def test_small_urban_sentinel_maps_to_small_urban_subcategory():
    cost = cp25_road_cost_usd_per_lane_mile(
        hpms_fclass=pd.Series([7]),
        urban=pd.Series([1]),
        urban_size_tier=pd.Series(["small_urban"]),
    )
    assert not cost.isna().any()


def test_improvement_type_override_selects_different_row():
    resurface = cp25_road_cost_usd_per_lane_mile(
        hpms_fclass=pd.Series([1]),
        urban=pd.Series([0]),
        urban_size_tier=pd.Series([pd.NA]),
        terrain_type=pd.Series(["Flat"]),
        improvement_type="Resurface Existing Lane",
    )
    reconstruct = cp25_road_cost_usd_per_lane_mile(
        hpms_fclass=pd.Series([1]),
        urban=pd.Series([0]),
        urban_size_tier=pd.Series([pd.NA]),
        terrain_type=pd.Series(["Flat"]),
        improvement_type="Total Reconstruct Existing Lane",
    )
    assert resurface.iloc[0] < reconstruct.iloc[0]


def test_boolean_mask_sliced_subset_with_noncontiguous_index():
    """Real caller pattern (scripts/3_damage_analysis.py's
    calculate_damage_sourced): road_links.loc[is_road, col] produces a
    Series whose index is the ORIGINAL non-contiguous row labels, not a
    fresh 0..n-1 range -- this must not raise or silently misalign."""
    df = pd.DataFrame(
        {
            "hpms_fclass": [1, 4, 1, 7],
            "urban": [0, 1, 0, 1],
            "urban_size_tier": [pd.NA, "large_urbanized", pd.NA, "small_urban"],
            "is_road": [True, False, True, True],
        }
    )
    is_road = df["is_road"]
    cost = cp25_road_cost_usd_per_lane_mile(
        hpms_fclass=df.loc[is_road, "hpms_fclass"],
        urban=df.loc[is_road, "urban"],
        urban_size_tier=df.loc[is_road, "urban_size_tier"],
    )
    assert len(cost) == 3
    assert not cost.isna().any()


def test_all_seven_fclasses_resolve_in_both_regions():
    for fclass in range(1, 8):
        rural = cp25_road_cost_usd_per_lane_mile(
            hpms_fclass=pd.Series([fclass]), urban=pd.Series([0]),
            urban_size_tier=pd.Series([pd.NA]),
        )
        urban = cp25_road_cost_usd_per_lane_mile(
            hpms_fclass=pd.Series([fclass]), urban=pd.Series([1]),
            urban_size_tier=pd.Series(["large_urbanized"]),
        )
        assert not rural.isna().any(), f"fclass {fclass} rural unresolved"
        assert not urban.isna().any(), f"fclass {fclass} urban unresolved"
