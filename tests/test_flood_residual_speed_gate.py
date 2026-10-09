"""Tests for T27-driven flood residual-speed-restriction gating.

The real production recovery-schedule day checkpoints are 0, 7, 14, 30, 60,
90 (parameters/tables/T26_recovery_design_current.csv / the data bundle's
recovery design_updated.csv) -- none of which are 1, 2, or 3. This is the
regression check for the dead-code bug that discovery fixed.
"""

from __future__ import annotations

from resiflow.tables import flood_residual_speed_gate


def test_day_0_is_all_flooded_segments():
    assert flood_residual_speed_gate(0) == "all"


def test_days_1_to_3_are_intermediate_and_deep():
    assert flood_residual_speed_gate(1) == "intermediate_and_deep"
    assert flood_residual_speed_gate(2) == "intermediate_and_deep"
    assert flood_residual_speed_gate(3) == "intermediate_and_deep"


def test_days_4_to_7_are_deep_only():
    assert flood_residual_speed_gate(4) == "deep_only"
    assert flood_residual_speed_gate(7) == "deep_only"


def test_day_8_and_beyond_is_none():
    assert flood_residual_speed_gate(8) == "none"
    assert flood_residual_speed_gate(30) == "none"


def test_real_production_schedule_checkpoints_all_resolve():
    """The exact real event_day values used in production
    (T26_recovery_design_current.csv / the data bundle) -- none of these
    are 1, 2, or 3, which is exactly why the old hardcoded `if event_day ==
    1/2/3` check never fired in any real run."""
    for day, expected in [(0, "all"), (7, "deep_only"), (14, "none"), (30, "none"), (60, "none"), (90, "none")]:
        assert flood_residual_speed_gate(day) == expected
