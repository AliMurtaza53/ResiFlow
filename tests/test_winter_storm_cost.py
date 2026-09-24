"""Tests for hazards/winter_storm_cost.py's T32 direct cleanup cost formula."""

from __future__ import annotations

import pytest

from resiflow.hazards.winter_storm_cost import winter_storm_direct_cost_usd_per_lane_mile

# T32's own 5 worked examples (snow_depth_mm, duration_hours, air_temp_F,
# road class -> "major"/"minor", expected USD/lane-mile adj) -- reproduced
# exactly from parameters/tables/T32_winter_storm_direct_cost_function.csv's
# own worked-example block.
_WORKED_EXAMPLES = [
    (150, 12, 28, "motorway", 304.92),
    (75, 6, 30, "motorway", 195.6),
    (300, 24, 20, "trunk", 600.0),
    (600, 36, 10, "residential", 426.86999999999995),
    (50, 8, 32, "residential", 96.55999999999999),
]


@pytest.mark.parametrize("depth,duration,temp,road_classification,expected", _WORKED_EXAMPLES)
def test_reproduces_t32_worked_examples_exactly(depth, duration, temp, road_classification, expected):
    cost = winter_storm_direct_cost_usd_per_lane_mile(
        snow_depth_mm=depth, duration_hours=duration, air_temp_F=temp, road_classification=road_classification
    )
    assert cost == pytest.approx(expected)


def test_zero_or_missing_depth_returns_zero():
    for depth in (None, 0.0, -5.0, float("nan")):
        assert winter_storm_direct_cost_usd_per_lane_mile(
            snow_depth_mm=depth, duration_hours=12, air_temp_F=28, road_classification="motorway"
        ) == 0.0


def test_missing_duration_falls_back_to_depth_only_floor():
    with_duration = winter_storm_direct_cost_usd_per_lane_mile(
        snow_depth_mm=150, duration_hours=12, air_temp_F=28, road_classification="motorway"
    )
    without_duration = winter_storm_direct_cost_usd_per_lane_mile(
        snow_depth_mm=150, duration_hours=None, air_temp_F=28, road_classification="motorway"
    )
    # duration/cycle_hours=4 dominates depth/d_plow_mm=3 in this example, so
    # dropping duration must not increase cost above the full-data case.
    assert without_duration <= with_duration
    assert without_duration > 0.0


def test_missing_temperature_falls_back_to_no_penalty():
    cold = winter_storm_direct_cost_usd_per_lane_mile(
        snow_depth_mm=600, duration_hours=36, air_temp_F=10, road_classification="motorway"
    )
    unknown_temp = winter_storm_direct_cost_usd_per_lane_mile(
        snow_depth_mm=600, duration_hours=36, air_temp_F=None, road_classification="motorway"
    )
    assert unknown_temp < cold  # T_factor=1.0 (no penalty) vs. the real cold-weather T_cap=2.0 multiplier
    assert unknown_temp > 0.0


def test_major_vs_minor_road_multiplier():
    major = winter_storm_direct_cost_usd_per_lane_mile(
        snow_depth_mm=150, duration_hours=12, air_temp_F=28, road_classification="secondary"
    )
    minor = winter_storm_direct_cost_usd_per_lane_mile(
        snow_depth_mm=150, duration_hours=12, air_temp_F=28, road_classification="residential"
    )
    assert major == pytest.approx(minor / 0.85 * 2.00)
