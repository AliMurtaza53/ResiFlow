"""Residual speed schedule helpers (T37/T38)."""
from __future__ import annotations

from resiflow.tables import residual_speed_factor


def test_earthquake_bridge_moderate_rises_to_one():
    f0 = residual_speed_factor(
        hazard="earthquake", asset="bridge", damage_level="moderate", event_day=0
    )
    f30 = residual_speed_factor(
        hazard="earthquake", asset="bridge", damage_level="moderate", event_day=30
    )
    assert f0 == 0.30
    assert f30 == 1.0


def test_landslide_road_minor_day3_full():
    assert (
        residual_speed_factor(
            hazard="landslide", asset="road", damage_level="minor", event_day=3
        )
        == 1.0
    )


def test_extensive_defers_to_t26_speed_one():
    assert (
        residual_speed_factor(
            hazard="earthquake", asset="bridge", damage_level="extensive", event_day=1
        )
        == 1.0
    )


def test_no_damage_is_one():
    assert (
        residual_speed_factor(
            hazard="earthquake", asset="road", damage_level="no", event_day=1
        )
        == 1.0
    )


def test_fast_reaches_full_sooner_than_average():
    avg = residual_speed_factor(
        hazard="earthquake",
        asset="bridge",
        damage_level="moderate",
        event_day=4,
        scenario="average",
    )
    fast = residual_speed_factor(
        hazard="earthquake",
        asset="bridge",
        damage_level="moderate",
        event_day=4,
        scenario="fast",
    )
    assert fast >= avg
